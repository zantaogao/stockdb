import sqlite3, statistics as st
from scipy.stats import linregress

sig = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro", uri=True)
rows = sig.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 20").fetchall()[::-1]
cols = list(zip(*[r[1:] for r in rows]))
print("20哨兵日斜率检验 (linregress):")
for name, c in zip(("fusion","reg10","reg20","reg40"), cols):
    lr = linregress(range(len(c)), c)
    print(f"{name}: 斜率{lr.slope:+.4f}/日 p={lr.pvalue:.3f}")

# 按ISO周聚合
from collections import defaultdict
wk = defaultdict(lambda: defaultdict(list))
dates = [r[0] for r in rows]
for i, d in enumerate(dates):
    iso = d[:7] + "-W%02d" % int(d[8:10]) and None
import datetime
def iso_week(s):
    y,m,dd = int(s[:4]),int(s[5:7]),int(s[8:10])
    return datetime.date(y,m,dd).isocalendar()[:2]
wk = defaultdict(lambda: defaultdict(list))
for i, d in enumerate(dates):
    w = iso_week(d)
    for j,name in enumerate(("fusion","reg10","reg20","reg40")):
        wk[w][name].append(cols[j][i])
print("\n逐周均值 fusion/reg10/reg20/reg40 (n):")
for w in sorted(wk):
    m = [st.mean(wk[w][n]) for n in ("fusion","reg10","reg20","reg40")]
    print(f"{w[0]}-W{w[1]:02d}: " + " ".join(f"{v:+.3f}" for v in m), f"(n={len(wk[w]['fusion'])})")