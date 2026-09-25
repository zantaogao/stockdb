#!/usr/bin/env python3
"""对拍：20260803 cmmr最低十分位D1的20d超额，两脚本口径逐步比，找分歧点。"""
import sqlite3, duckdb, numpy as np
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
sd, end = '20260803', '20260831'
tdays = [str(r[0]) for r in td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY 1").fetchall()]
print('tidx差:', tdays.index(end) - tdays.index(sd), '(应=20)')
bad = set()
for sc, nm, mk in st.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))
sig = st.execute("SELECT stock_code, cmmr_score FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
print('信号行数:', len(sig), ' 去重票数:', len({c for c, _ in sig}))
p0 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (sd,)).fetchall()}
p1 = {r[0]: float(r[1]) for r in td.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (end,)).fetchall()}
mret = np.mean([(p1[t] / p0[t] - 1) * 100 for t in p0 if t in p1 and t[:6] not in bad and p0[t] > 0])
data = []
for code, cs in sig:
    ts = code + ('.SH' if code.startswith(('6', '9')) else '.SZ')
    if ts in p0 and ts in p1 and p0[ts] > 0 and code not in bad:
        data.append((float(cs or 0), (p1[ts] / p0[ts] - 1) * 100, code))
data.sort()
n = len(data)
d1 = data[:n // 10]
print(f'n={n} 市场20d={mret:+.2f}%')
print(f'D1(n={len(d1)}): 分数范围 {d1[0][0]:.1f}~{d1[-1][0]:.1f} 原始均值={np.mean([v for _,v,_ in d1]):+.2f}% 超额={np.mean([v for _,v,_ in d1])-mret:+.2f}%')
# D1里最好和最差各5只
d1s = sorted(d1, key=lambda x: -x[1])
print('D1最好5:', [(c, round(v,1)) for _,v,c in d1s[:5]])
print('D1最差5:', [(c, round(v,1)) for _,v,c in d1s[-5:]])
# 分数并列检查：D1边界是不是有大批同分票
from collections import Counter
cnt = Counter(float(cs or 0) for _, cs in sig)
print('cmmr分数值分布 top8:', cnt.most_common(8))