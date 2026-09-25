#!/usr/bin/env python3
"""修正版事件研究：cmmr_score只有6档(0/20/40/60/80/100)，十分位并列抽签失真。
改按整档分组（不并列抽签）：Z=0分 / S=20~40 / M=60~80 / T=100。
各组等权持有H1~H20逐日超额（减全市场等权）。回答：0分票（跌最惨没人要）要套多久。"""
import sqlite3, duckdb, numpy as np
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tdays = [str(r[0]) for r in td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY 1").fetchall()]
tidx = {d: i for i, d in enumerate(tdays)}
sig_dates = [str(r[0]) for r in st.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
mature = [d for d in sig_dates if d in tidx and tidx[d] + 20 < len(tdays)]
bad = set()
for sc, nm, mk in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))

def closes_on(d):
    return {r[0]: float(r[1]) for r in td.execute(
        "SELECT ts_code, close FROM daily WHERE trade_date=?", (d,)).fetchall()}

H = 20
paths = {g: {h: [] for h in range(1, H + 1)} for g in ('Z', 'S', 'M', 'T')}
sizes = {g: [] for g in ('Z', 'S', 'M', 'T')}
days_used = []
for sd in mature:
    sig = st.execute("SELECT stock_code, cmmr_score FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    if not sig or len({float(s or 0) for _, s in sig}) < 5:
        continue
    p0_all = closes_on(sd)
    px = [closes_on(tdays[tidx[sd] + h]) for h in range(H + 1)]
    uni = [t for t in p0_all if p0_all[t] > 0 and t[:6] not in bad]
    mkt = {h: np.mean([(px[h][t] / p0_all[t] - 1) * 100 for t in uni if t in px[h] and px[h][t] > 0])
           for h in range(H + 1)}
    grp = {'Z': [], 'S': [], 'M': [], 'T': []}
    for code, cs in sig:
        ts = code + ('.SH' if code.startswith(('6', '9')) else '.SZ')
        if ts not in p0_all or p0_all[ts] <= 0 or code in bad:
            continue
        s = float(cs or 0)
        g = 'Z' if s == 0 else ('S' if s <= 40 else ('M' if s <= 80 else 'T'))
        if all(ts in px[h] and px[h][ts] > 0 for h in range(H + 1)):
            grp[g].append(ts)
    days_used.append(sd)
    for g, glist in grp.items():
        sizes[g].append(len(glist))
        if not glist:
            continue
        for h in range(1, H + 1):
            r = np.mean([(px[h][t] / p0_all[t] - 1) * 100 for t in glist])
            paths[g][h].append(r - mkt[h])

print(f'信号日={len(days_used)} 个: {days_used}')
print('组均票数: ' + "  ".join(f"{g}={np.mean(sizes[g]):.0f}" for g in ('Z','S','M','T')))
hs = [1, 2, 3, 5, 7, 10, 13, 15, 17, 20]
for g in ('Z', 'S', 'M', 'T'):
    vals = [np.mean(paths[g][h]) if paths[g][h] else np.nan for h in hs]
    fp = next((h for h in range(1, 21) if paths[g][h] and np.mean(paths[g][h]) > 0), None)
    worst_h = min(range(1, 21), key=lambda h: np.mean(paths[g][h]) if paths[g][h] else 0)
    print(f'{g} 逐日超额%: ' + " ".join(f"H{h}={v:+5.2f}" for h, v in zip(hs, vals)) +
          f" | 首个转正日={('H'+str(fp)) if fp else '20天内未转正'} 最深={np.mean(paths[g][worst_h]):+.2f}(H{worst_h}) 终点H20={np.mean(paths[g][20]):+.2f}")