#!/usr/bin/env python3
"""对照分析: 7/24 top10 的 7/30 表现 + 市场基准 + 满分股整体 2026-08-08"""
import sqlite3, duckdb

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
sd = '20260724'

s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

def code_to_ts(c):
    return f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"

# 1. 市场基准: 7/24 -> 8/7 全市场等权 + 各日
tds = [r[0] for r in t.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
i0 = tds.index(sd); end = tds[i0 + 10]
mkt0 = t.execute("SELECT AVG(close) FROM daily WHERE trade_date=?", (sd,)).fetchone()[0]
mktn = t.execute("SELECT AVG(close) FROM daily WHERE trade_date=?", (end,)).fetchone()[0]
print(f"全市场平均价: {sd}={mkt0:.2f} -> {end}={mktn:.2f} = {(mktn/mkt0-1)*100:+.2f}%")
# 中位数更稳
import statistics
c0 = [r[0] for r in t.execute("SELECT close FROM daily WHERE trade_date=? AND close>0", (sd,)).fetchall()]
cn = [r[0] for r in t.execute("SELECT close FROM daily WHERE trade_date=? AND close>0", (end,)).fetchall()]
m0, mn = statistics.median(c0), statistics.median(cn)
print(f"全市场收盘中位数: {m0:.2f} -> {mn:.2f} = {(mn/m0-1)*100:+.2f}%")
# 上证指数
idx0 = t.execute("SELECT close FROM index_daily_raw WHERE ts_code='000001.SH' AND trade_date=?", (sd,)).fetchone()
idxn = t.execute("SELECT close FROM index_daily_raw WHERE ts_code='000001.SH' AND trade_date=?", (end,)).fetchone()
if idx0 and idxn:
    print(f"上证指数: {idx0[0]} -> {idxn[0]} = {(float(idxn[0])/float(idx0[0])-1)*100:+.2f}%")

# 2. 7/30 大跌日市场
d30 = '20260730'
d29 = '20260729'
c29 = [r[0] for r in t.execute("SELECT close FROM daily WHERE trade_date=? AND close>0", (d29,)).fetchall()]
c30 = [r[0] for r in t.execute("SELECT close FROM daily WHERE trade_date=? AND close>0", (d30,)).fetchall()]
med29, med30 = statistics.median(c29), statistics.median(c30)
print(f"\n7/30 市场: 中位数 {(med30/med29-1)*100:+.2f}%")

# 3. 7/24 满分股(100分)整体 7/24->8/7 收益（对照组）
rows = s.execute("SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? AND fusion_3f_score=100", (sd,)).fetchall()
sh_codes = {r[0] for r in s.execute("SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()}
rets = []
for c, sc, sig in rows:
    if c not in sh_codes:
        continue
    ts = code_to_ts(c)
    p0 = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (sd, ts)).fetchone()
    pn = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (end, ts)).fetchone()
    if p0 and pn and p0[0] and pn[0]:
        rets.append((float(pn[0])/float(p0[0])-1)*100)
print(f"\n7/24 满分股(100分, signal_history∩) {len(rets)} 只, 等权10日: {statistics.mean(rets):+.2f}%, 中位: {statistics.median(rets):+.2f}%")
print(f"  正收益占比: {sum(1 for r in rets if r>0)/len(rets)*100:.0f}%")

# 4. 7/24 强买整体（731只）
rows2 = s.execute("SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? AND signal='强买'", (sd,)).fetchall()
rets2 = []
for c, sc, sig in rows2:
    if c not in sh_codes:
        continue
    ts = code_to_ts(c)
    p0 = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (sd, ts)).fetchone()
    pn = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (end, ts)).fetchone()
    if p0 and pn and p0[0] and pn[0]:
        rets2.append((float(pn[0])/float(p0[0])-1)*100)
print(f"7/24 强买整体(滤ST后) {len(rets2)} 只, 等权10日: {statistics.mean(rets2):+.2f}%, 中位: {statistics.median(rets2):+.2f}%")
print(f"  正收益占比: {sum(1 for r in rets2 if r>0)/len(rets2)*100:.0f}%")

# 5. Top10 的 7/30 单日
top10 = ['603400','301213','301067','300427','301552','300940','600538','000668','002388','002012']
print(f"\nTop10 在 7/30 大跌日:")
tot = 0
for c in top10:
    ts = code_to_ts(c)
    r1 = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (d29, ts)).fetchone()
    r2 = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (d30, ts)).fetchone()
    if r1 and r2 and r1[0] and r2[0]:
        r = (float(r2[0])/float(r1[0])-1)*100
        tot += r
        print(f"  {c}: {r:+.2f}%")
print(f"  等权: {tot/10:+.2f}%")
t.close(); s.close()
