# -*- coding: utf-8 -*-
"""追差异根因：取 20260918 若干差异票，手工重算三因子 vs 我的矩阵值 vs 生产值"""
import duckdb, sqlite3, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
sc = sqlite3.connect(f'file:{HOME}/.hermes/stockdb/signals.db?mode=ro', uri=True)

d = '20260918'
sig = {r[0]: r[1] for r in sc.execute(
    f"SELECT stock_code, cmmr_score FROM signal_history WHERE REPLACE(date,'-','')='{d}' AND cmmr_score>0").fetchall()}

diff_codes = []
for code, cs in sig.items():
    ts = code if '.' in code else code + ('.SH' if code[:1] in ('6','9') else ('.BJ' if code[:1] in ('4','8') else '.SZ'))
    rows = con.execute(f"""select trade_date, "open", close, vol from daily
        where ts_code='{ts}' and trade_date<='{d}' order by trade_date desc limit 62""").fetchall()
    if len(rows) < 62: continue
    rows = rows[::-1]
    closes = [r[2] for r in rows]; vols = [r[3] for r in rows]; opens = [r[1] for r in rows]
    ma40 = np.mean(closes[-40:]); ma40_lag = np.mean(closes[-60:-20])
    slope = (ma40-ma40_lag)/ma40_lag
    p10 = closes[-1]/closes[-11]-1
    vr = vols[-1]/(np.mean(vols[-5:]))
    t_ = 40 if slope>0.02 else (20 if slope>0 else 0)
    o_ = 40 if p10<-0.08 else (20 if p10<-0.04 else 0)
    v_ = 20 if (vr<0.8 or (vr>1.2 and closes[-1]>opens[-1])) else 0
    mine = 0 if slope<0 else t_+o_+v_
    if abs(mine-cs) > 1e-6:
        diff_codes.append((code, cs, mine, round(slope,4), round(p10,4), round(vr,3), t_, o_, v_))
print(f'{d} 差异票 {len(diff_codes)}/{len(sig)}')
for r in diff_codes[:12]: print(r)
# 差异票的因子临界性
import collections
c = collections.Counter()
for code, cs, mine, slope, p10, vr, *_ in diff_codes:
    dlt = mine - cs
    c[dlt] += 1
print('分差分布:', dict(c))
# 临界性：差异票里 slope/p10/vr 落在阈值±0.5%容差内的比例
near = sum(1 for r in diff_codes if abs(r[3]-0.02)<1e-4 or abs(r[4]+0.08)<2e-4 or abs(r[4]+0.04)<2e-4 or abs(r[5]-0.8)<0.01 or abs(r[5]-1.2)<0.01)
print('因子贴近阈值的差异票:', near, '/', len(diff_codes))
