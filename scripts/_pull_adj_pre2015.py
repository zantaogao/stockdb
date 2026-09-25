# -*- coding: utf-8 -*-
"""补 2009-2014 年 adj_factor（tushare API → 分片 parquet 补丁，不写主库）

背景（2026-09-21 发现）：两台 tushare.db 的 adj_factor 表只有 2015-01 起的数据，
2009-2014 覆盖率 0.0% → 任何"17 年"回测的前 6 年（1152 交易日 ≈ 30% 样本）在用未复权价
或跳变价（v1 事故：假收益几千 % 把均值基准拉成 +14161%）。

做法：按交易日逐日调 pro.adj_factor(trade_date=...)，每 100 天写一个分片 parquet
（可续传，中断不丢已完成部分），最后 merge 成单个文件：
  ~/.hermes/stockdb/backtest_results/adj_factor_pre2015.parquet
消费端（回测脚本）以 UNION 方式读取补丁 + 主库，主库保持只读。
"""
import glob
import json
import os
import time

import duckdb
import pandas as pd
import tushare as ts

BASE = os.path.expanduser('~/.hermes/stockdb')
PARTDIR = f'{BASE}/backtest_results/adj_pre2015_parts'
OUT = f'{BASE}/backtest_results/adj_factor_pre2015.parquet'
START, END = '20090101', '20150101'
os.makedirs(PARTDIR, exist_ok=True)

cfg = json.load(open(f'{BASE}/config.json'))
ts.set_token(cfg.get('tushare_token', ''))
pro = ts.pro_api()

con = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
days = [r[0] for r in con.execute(
    f"SELECT DISTINCT trade_date FROM daily WHERE trade_date>='{START}' AND trade_date<'{END}' "
    "ORDER BY trade_date").fetchall()]
con.close()

done = set()
for f in glob.glob(f'{PARTDIR}/part_*.parquet'):
    tag = os.path.basename(f).replace('part_', '').replace('.parquet', '')
    done.add(tag)
todo = [d for d in days if d not in done]
print(f'交易日 {len(days)}  已完成分片 {len(done)}  待拉 {len(todo)}', flush=True)

buf, t0, ok, fail = [], time.time(), 0, 0
for k, d in enumerate(todo, 1):
    df = None
    for _ in range(3):
        try:
            df = pro.adj_factor(trade_date=d)
            break
        except Exception as e:  # noqa: BLE001
            print(f'  {d} 异常 {e}，重试', flush=True)
            time.sleep(3)
    if df is None or len(df) == 0:
        fail += 1
        print(f'  ⚠️ {d} 无数据/失败（跳过）', flush=True)
        continue
    buf.append(df[['ts_code', 'trade_date', 'adj_factor']])
    ok += 1
    if len(buf) >= 100 or k == len(todo):
        part = pd.concat(buf, ignore_index=True)
        first, last = part.trade_date.iloc[0], part.trade_date.iloc[-1]
        part.to_parquet(f'{PARTDIR}/part_{first}_{last}.parquet', index=False)
        print(f'  [{k}/{len(todo)}] 写分片 {first}~{last}（{len(part)} 行）'
              f'  已用 {time.time()-t0:.0f}s', flush=True)
        buf = []
    time.sleep(0.12)

files = sorted(glob.glob(f'{PARTDIR}/part_*.parquet'))
if files:
    allp = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    allp = allp.drop_duplicates(subset=['ts_code', 'trade_date'])
    allp.to_parquet(OUT, index=False)
    print(f'\n合并 {len(files)} 个分片 → {OUT}', flush=True)
    print(f'  行数 {len(allp):,}  票数 {allp.ts_code.nunique():,}  '
          f'日期 {allp.trade_date.min()}~{allp.trade_date.max()}', flush=True)
    print(f'  成功 {ok} 天 / 失败 {fail} 天 / 总耗时 {time.time()-t0:.0f}s', flush=True)
else:
    print('无分片可合并', flush=True)
