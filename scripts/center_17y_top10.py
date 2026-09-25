#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中枢版（fusion_center）17 年**逐日 top10 名单**重建 —— 2026-09-21

背景：给「窗口内现金政策」回测提供**生产口径、17 年可复现**的名单。
  上一轮同实验用的是 CMMR 名单 —— 那是负 alpha 名单（年化 −18.6%），
  在负 alpha 名单上"买得越多亏得越多"是必然，测不出"该不该补仓"。
  本次换成中枢版名单：纯量价、17 年可复算、且 9/11 独立验证过是正 alpha
  （top10 10 日 +0.659% vs 市场 +0.322%，超额 +0.337pp/10 日）。

口径严格照 fusion_center_engine.py（生产）+ center_17y_long.py（历史复算）：
  ma   = ((close-c4)/c4 - (close-c6)/c6) / |(close-c6)/c6|        c4=LAG4, c6=LAG6
  flow = sqrt(vol/vol5) * ret1 * (1+|ret1*100|/100)
  vola = (std5(close)/avg5(close)) / (std5(vol)/avg5(vol))
  剔除 ST / 北交所 / 代码 8 或 4 开头
  稳健 z：当日 1%-99% 分位截断 → 当日截面 mean/std(ddof=1)
  score = -(|ma_z| + |flow_z| + |vola_z|)      ← 三因子离截面中枢越近越好
  强买 = 当日 rank_pct >= 0.85
  **名单 = 强买池内 score 最大的 10 只**（= 生产 `df[df.signal=='强买'].nlargest(10,'score')`）

输出：backtest_results/center_17y_top10.parquet
  列：date(YYYYMMDD, str) | rank(1..10) | ts_code | score
自检：脚本内用同名口径重算 top10 的 10 日前瞻收益，与 center_17y_long_20260911_daily.csv
      的 top10 列对比（相关系数应 > 0.95，否则说明口径漂了）。
"""
import os
import time

import duckdb
import numpy as np
import pandas as pd

BASE = os.path.expanduser('~/.hermes/stockdb')
_TOP_N = int(os.environ.get('TOP_N', '10'))   # 目标只数（敏感性测试用：10/15/20）
T = f'{BASE}/tushare.db'
OUT = f'{BASE}/backtest_results/center_17y_top{_TOP_N}.parquet'
REF = f'{BASE}/backtest_results/center_17y_long_20260911_daily.csv'

# (统计区间, 前置取数起点) —— 前置 ≥40 交易日，供 LAG6 与 5 日窗口预热
CHUNKS = [('20100101', '20131231', '20091101'),
          ('20140101', '20171231', '20131101'),
          ('20180101', '20211231', '20171101'),
          ('20220101', '20260930', '20211101')]

t0 = time.time()
con = duckdb.connect(T, read_only=True)
RAM = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1e9
con.execute(f"SET memory_limit='{max(2, min(24, int(RAM * 0.6)))}GB'; "
            "SET threads=4; SET temp_directory='/tmp/ddspill';")
print(f'内存上限 {max(2, min(24, int(RAM * 0.6)))}GB  主机内存 {RAM:.0f}GB', flush=True)

outs, chk = [], []
for i, (rlo, rhi, lo) in enumerate(CHUNKS, 1):
    t1 = time.time()
    q = f"""
    WITH b AS (
      SELECT d.ts_code, d.trade_date, d.close, d.vol,
        LAG(d.close,4) OVER w AS c4, LAG(d.close,6) OVER w AS c6, LAG(d.close,1) OVER w AS pc,
        AVG(d.close) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS pa,
        STDDEV(d.close) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ps,
        AVG(d.vol)   OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS va,
        STDDEV(d.vol)OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS vs,
        LEAD(d.close,10) OVER w AS f10c
      FROM daily d WHERE d.trade_date BETWEEN '{lo}' AND '{rhi}'
      WINDOW w AS (PARTITION BY d.ts_code ORDER BY d.trade_date)
    )
    SELECT b.*, CASE WHEN sb.name LIKE '%ST%' OR sb.market='北交所' OR b.ts_code LIKE '8%' OR b.ts_code LIKE '4%'
                     THEN 1 ELSE 0 END AS is_bad
    FROM b LEFT JOIN stock_basic sb ON sb.ts_code = b.ts_code
    """
    df = con.execute(q).df()
    df = df[df['is_bad'] == 0]
    df = df[(df['trade_date'] >= rlo) & (df['trade_date'] <= rhi)].copy()

    ret1 = df['close'] / df['pc'] - 1
    df['ma'] = (((df['close'] - df['c4']) / df['c4'] - (df['close'] - df['c6']) / df['c6'])
                / ((df['close'] - df['c6']) / df['c6']).abs())
    df['flow'] = np.sqrt(df['vol'] / df['va']) * ret1 * (1 + (ret1 * 100).abs() / 100)
    df['vola'] = (df['ps'] / df['pa']) / (df['vs'] / df['va'])
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=['ma', 'flow', 'vola'])

    for c in ['ma', 'flow', 'vola']:
        lo_q = df.groupby('trade_date')[c].transform(lambda s: s.quantile(0.01))
        hi_q = df.groupby('trade_date')[c].transform(lambda s: s.quantile(0.99))
        df[c] = df[c].clip(lo_q, hi_q)
        g = df.groupby('trade_date')[c]
        df[c + '_z'] = (df[c] - g.transform('mean')) / g.transform(lambda s: s.std(ddof=1))

    df['score'] = -(df['ma_z'].abs() + df['flow_z'].abs() + df['vola_z'].abs())
    df['rp'] = df.groupby('trade_date')['score'].rank(pct=True)
    df['fwd10'] = (df['f10c'] / df['close'] - 1) * 100

    qb = df[df['rp'] >= 0.85].copy()                     # 强买池
    qb['rk'] = qb.groupby('trade_date')['score'].rank(ascending=False, method='first')
    top = qb[qb['rk'] <= _TOP_N].copy()                  # 强买池内前 N = 生产口径

    outs.append(top[['trade_date', 'rk', 'ts_code', 'score']])
    chk.append(pd.DataFrame({
        'date': top.groupby('trade_date').size().index.astype(str),
        'n_top': top.groupby('trade_date').size().values,
        'top10_fwd10': top.groupby('trade_date')['fwd10'].mean().values,
        'mkt_fwd10': df.groupby('trade_date')['fwd10'].mean().reindex(
            top.groupby('trade_date').size().index).values,
    }))
    print(f'[{i}/4] {rlo}~{rhi}: 行 {len(df):,} → 名单 {len(top):,} 只·日  '
          f'{time.time() - t1:.0f}s', flush=True)

con.close()
TOP = pd.concat(outs, ignore_index=True)
TOP['date'] = TOP['trade_date'].astype(str)
TOP = (TOP.rename(columns={'rk': 'rank'})[['date', 'rank', 'ts_code', 'score']]
          .sort_values(['date', 'rank']).reset_index(drop=True))
TOP['rank'] = TOP['rank'].astype(int)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
TOP.to_parquet(OUT, index=False)
print(f'\n✅ 名单 {len(TOP):,} 行 → {OUT}')
print(f'   日期 {TOP.date.min()} ~ {TOP.date.max()}   交易日 {TOP.date.nunique():,}   '
      f'涉及个股 {TOP.ts_code.nunique():,} 只')

C = pd.concat(chk, ignore_index=True)
if os.path.exists(REF):
    R = pd.read_csv(REF, dtype={'date': str})
    M = C.merge(R[['date', 'top10', 'mkt10']], on='date', how='inner')
    if len(M) > 100:
        print(f'\n=== 口径自检（对 center_17y_long_20260911_daily.csv，重叠 {len(M):,} 天）===')
        print(f'  top10 10日收益：我 {M.top10_fwd10.mean():+.3f}%  参考 {M.top10.mean():+.3f}%   '
              f'相关 {M.top10_fwd10.corr(M.top10):.4f}')
        print(f'  全市场 10日收益：我 {M.mkt_fwd10.mean():+.3f}%  参考 {M.mkt10.mean():+.3f}%   '
              f'相关 {M.mkt_fwd10.corr(M.mkt10):.4f}')
        print(f'  每日名单只数：均值 {M.n_top.mean():.2f}  最小 {M.n_top.min()}  最大 {M.n_top.max()}')
        print('  判定：相关系数 >0.95 视为口径一致；若 <0.9 需查因子定义差异')
print(f'总耗时 {time.time() - t0:.0f}s')
