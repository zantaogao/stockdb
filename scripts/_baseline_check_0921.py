# -*- coding: utf-8 -*-
"""基准口径核验：横截面中位数 vs 等权均值（2026-09-21）

动机：9/20 CMMR 权重网格用 `nanmedian(fwd_all)`（全可交易域 10 日前向收益的横截面中位数）
作基准算"超额"。但中位数不是可投资组合——真正能买的是"等权全市场"（均值）。
A 股收益横截面右偏（少数票暴涨、多数微跌）→ 中位数 << 均值 → 用中位数当基准会**高估超额**。

本脚本在同一批 2015+ 数据、同一批非重叠信号日上，并列给出：
  横截面中位数（9/20 基准） / 等权均值（可投资基准） / CMMR 40-40-20 top10 组合
及其超额，验证符号是否反转。
"""
import os
import sqlite3
import time

import duckdb
import numpy as np
import pandas as pd

HOME = os.path.expanduser('~')
DB = f'{HOME}/.hermes/stockdb/tushare.db'
SIG = f'{HOME}/.hermes/stockdb/signals.db'
START = '20150101'
FWD = 10
COST = 0.002  # 双边

t0 = time.time()
con = duckdb.connect(DB, read_only=True)
con.execute("SET memory_limit='24GB'")
bad = set()
sc = sqlite3.connect(f'file:{SIG}?mode=ro', uri=True)
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8', '4', '92')):
        bad.add(str(code))
sc.close()
df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) AS td, d."open", d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date >= '{START}'
""").df()
con.close()
df = df[~df.ts_code.str[:6].isin(bad)]
col_order = sorted(df.ts_code.unique())


def piv(col):
    return (df.pivot(index='td', columns='ts_code', values=col)
              .reindex(columns=col_order).astype('float32'))


close = piv('close')
opn = piv('open')
vol = piv('vol')
adjf = piv('adj_factor').ffill()
_rw = (close * adjf).values
_rr = np.zeros_like(_rw)
_rr[1:] = np.where(_rw[:-1] > 0, _rw[1:] / np.where(_rw[:-1] > 0, _rw[:-1], np.nan) - 1, np.nan)
_bad = np.abs(np.nan_to_num(_rr, nan=0.0)) > 0.21
A_ff = pd.DataFrame(np.where(_bad, np.nan, _rw), index=close.index).ffill().values
cal = list(close.index)
n = len(cal)
print(f'cal {n} {cal[0]}->{cal[-1]}  异常夹紧 {int(_bad.sum())} 样本  {time.time()-t0:.0f}s', flush=True)

ma40 = close.rolling(40).mean()
ma40p = close.rolling(20).mean().shift(40)
S = ((ma40 - ma40p) / ma40p).values
P = (close / close.shift(10) - 1).values
R_ = (vol / vol.rolling(5).mean()).values
enough = (close.rolling(60).count().values >= 60)
O_, C_ = opn.values, close.values
T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0)).astype('float32')
Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0)).astype('float32')
V = np.where((R_ < 0.8) | ((R_ > 1.2) & (C_ > O_)), 1.0, 0.0).astype('float32')
kill = (S < 0) | ~enough | np.isnan(C_)
T[kill] = 0
Ov[kill] = 0
V[kill] = 0
SCORE = (40 * T + 40 * Ov + 20 * V) / 100.0

rows = []
for i in range(60, n - FWD - 1, FWD):        # 非重叠信号日
    fwd = A_ff[i + FWD] / np.where(A_ff[i] > 0, A_ff[i], np.nan) - 1
    fwd = np.where(np.isnan(A_ff[i]) | np.isnan(A_ff[i + FWD]), np.nan, fwd)
    fwd = np.where(np.abs(fwd) > 1.0, np.nan, fwd)      # 防残留数据缺口
    ok = ~np.isnan(fwd)
    if ok.sum() < 500:
        continue
    med = float(np.nanmedian(fwd[ok]))
    mean = float(np.nanmean(fwd[ok]))
    srow = SCORE[i]
    pool = np.where(srow >= 0.8)[0]
    top = np.nan
    if len(pool) >= 10:
        ps, pp = srow[pool], P[i, pool]
        sel = ~np.isnan(pp)
        ps, pp, idx = ps[sel], pp[sel], pool[sel]
        if len(ps) >= 10:
            order = np.lexsort((pp, -ps))[:10]
            f = fwd[idx[order]]
            f = f[~np.isnan(f)]
            if len(f) >= 8:
                top = float(f.mean())
    rows.append(dict(date=cal[i], med=med, mean=mean, top=top,
                     n=int(ok.sum()), year=cal[i] // 10000))

D = pd.DataFrame(rows)
print(f'非重叠样本 {len(D)} 个信号日（{D.date.iloc[0]} → {D.date.iloc[-1]}）\n')

print('=' * 96)
print('【基准口径核验】每 10 日一次，非重叠（%，含双边成本 0.2% 的已单列）')
print('=' * 96)
print(f"{'口径':<28}{'10日均值%':>12}{'年化%':>10}{'对中位超额pp':>14}{'对均值超额pp':>14}")
med_m = D['med'].mean() * 100
mean_m = D['mean'].mean() * 100
top_g = D['top'].mean() * 100
top_n = (D['top'] - COST).mean() * 100
ann = lambda r10: ((1 + r10 / 100) ** (243.0 / FWD) - 1) * 100
print(f"{'横截面中位数(9/20 基准)':<28}{med_m:>+12.3f}{ann(med_m):>+10.1f}{0.0:>+14.3f}{med_m-mean_m:>+14.3f}")
print(f"{'等权均值(可投资基准)':<28}{mean_m:>+12.3f}{ann(mean_m):>+10.1f}{mean_m-med_m:>+14.3f}{0.0:>+14.3f}")
print(f"{'CMMR top10(毛)':<28}{top_g:>+12.3f}{ann(top_g):>+10.1f}{top_g-med_m:>+14.3f}{top_g-mean_m:>+14.3f}")
print(f"{'CMMR top10(扣0.2%双边)':<28}{top_n:>+12.3f}{ann(top_n):>+10.1f}{top_n-med_m:>+14.3f}{top_n-mean_m:>+14.3f}")

print('\n' + '=' * 96)
print('【分年】中位数基准 vs 均值基准（10 日收益 %）')
print('=' * 96)
print(f"{'年':<8}{'中位':>10}{'均值':>10}{'top10':>10}{'top10-中位':>12}{'top10-均值':>12}{'n日':>6}")
for y, sub in D.groupby('year'):
    print(f"{y:<8}{sub['med'].mean()*100:>+10.3f}{sub['mean'].mean()*100:>+10.3f}{sub['top'].mean()*100:>+10.3f}"
          f"{(sub['top']-sub['med']).mean()*100:>+12.3f}{(sub['top']-sub['mean']).mean()*100:>+12.3f}{len(sub):>6}")
print(f"\n结论：中位数基准 {med_m:+.3f}%/10日 vs 可投资均值基准 {mean_m:+.3f}%/10日 —— "
      f"差 {med_m-mean_m:+.3f}pp；top10 对中位超额 {top_n-med_m:+.3f}pp，对均值超额 {top_n-mean_m:+.3f}pp")
D.to_csv(f'{HOME}/.hermes/stockdb/analysis/baseline_check_0921.csv', index=False)
print(f'明细 → ~/.hermes/stockdb/analysis/baseline_check_0921.csv   {time.time()-t0:.0f}s')
