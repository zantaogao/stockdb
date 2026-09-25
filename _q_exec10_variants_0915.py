#!/usr/bin/env /usr/bin/python3 -B
"""10日窗口执行端方案对拍: reg10排序 vs clf10参与的各种组合 (top10篮子10日实际收益)"""
import sqlite3, duckdb
import numpy as np, pandas as pd

BASE = '/Users/zantao/.hermes/stockdb'
FWD = 10
tcon = sqlite3.connect(BASE + '/signals.db')
dcon = duckdb.connect(BASE + '/tushare.db', read_only=True)
all_days = [str(r[0]) for r in dcon.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
pos = {d: i for i, d in enumerate(all_days)}
def tc(c): return f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ"
def px(d, codes):
    out = {}
    arr = [tc(c) for c in codes]
    for k in range(0, len(arr), 900):
        ch = arr[k:k+900]; ph = ','.join(['?']*len(ch))
        for t, c in dcon.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [d]+ch).fetchall():
            out[str(t)] = float(c)
    return out

sds = [str(r[0]) for r in tcon.execute("SELECT DISTINCT REPLACE(date,'-','') FROM shadow_clf10_scores ORDER BY 1").fetchall()]
sds = [s for s in sds if s in pos and pos[s]+FWD < len(all_days)]
print("可用成熟日:", len(sds), sds[0], "~", sds[-1])
variants = ['reg10纯排', 'clf否决<0.50', 'clf否决<P30', 'clf纯排', 'fusion腿对照']
res = {v: [] for v in variants}
for sd in sds:
    end = all_days[pos[sd]+FWD]
    r10 = {str(c): float(s) for c, s in tcon.execute("SELECT stock_code, reg10 FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()}
    fus = {str(c): float(s) for c, s in tcon.execute("SELECT stock_code, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()}
    clf = {str(c): float(s) for c, s in tcon.execute("SELECT code, score FROM shadow_clf10_scores WHERE date=?", (sd,)).fetchall()}
    codes = list(r10.keys())
    p0, p1 = px(sd, codes), px(end, codes)
    df = pd.DataFrame({'code': codes})
    df['ret'] = [(p1.get(tc(c), np.nan)/p0.get(tc(c), np.nan)-1) for c in df['code']]
    df['r10'] = df['code'].map(r10); df['clf'] = df['code'].map(clf); df['fus'] = df['code'].map(fus)
    d = df.dropna(subset=['ret','r10','clf'])
    if len(d) < 100: continue
    p30 = np.percentile(d['clf'], 30)
    res['reg10纯排'].append(d.nlargest(10,'r10')['ret'].mean())
    res['clf否决<0.50'].append(d[d['clf']>=0.50].nlargest(10,'r10')['ret'].mean())
    res['clf否决<P30'].append(d[d['clf']>=p30].nlargest(10,'r10')['ret'].mean())
    res['clf纯排'].append(d.nlargest(10,'clf')['ret'].mean())
    d2 = d.dropna(subset=['fus'])
    res['fusion腿对照'].append(d2.nlargest(10,'fus')['ret'].mean() if len(d2)>50 else np.nan)

import statistics as st
print(f"\n{'方案':<14}{'均值':>9}{'中位':>9}{'截尾(去2)':>10}{'正天':>8}")
for v in variants:
    s = [x for x in res[v] if x==x]
    srt = sorted(s)
    print(f"{v:<16}{st.mean(s)*100:>+8.2f}%{st.median(s)*100:>+8.2f}%{st.mean(srt[2:-2])*100 if len(srt)>4 else float('nan'):>+9.2f}%  {sum(1 for x in s if x>0)}/{len(s)}")
# paired: 否决P30 vs 纯排
a, b = res['clf否决<P30'], res['reg10纯排']
dd = [x-y for x,y in zip(a,b) if x==x and y==y]
m = st.mean(dd); t = m/(st.stdev(dd)/len(dd)**0.5)
print(f"\n否决<P30 - 纯排: 逐日差均值{m*100:+.3f}% t={t:+.2f} 否决更好{sum(1 for x in dd if x>0)}/{len(dd)}天")
a, b = res['clf否决<0.50'], res['reg10纯排']
dd = [x-y for x,y in zip(a,b) if x==x and y==y]
m = st.mean(dd); t = m/(st.stdev(dd)/len(dd)**0.5)
print(f"否决<0.50 - 纯排: 逐日差均值{m*100:+.3f}% t={t:+.2f} 否决更好{sum(1 for x in dd if x>0)}/{len(dd)}天")
