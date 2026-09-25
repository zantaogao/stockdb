#!/usr/bin/env python3
"""事件研究：cmmr全截面最低十分位(D1)组，信号日后1~20交易日的逐日路径。
每行=一个信号日：D1组等权累计收益(%)、等权市场基准累计收益(%)、超额(%)。
另附 D10(最高分组)与深度负分组(cmmr最低100只,若够)对照。
回答'要套多久'：看超额曲线第几天转正、中途最大回撤。"""
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
paths = {'D1': [], 'D10': [], 'NEG': []}   # 每列一 horizon 的日均超额
mkt_path = [[] for _ in range(H + 1)]
days_used = 0
for sd in mature:
    sig = st.execute("SELECT stock_code, cmmr_score FROM signal_history WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
    if not sig or len({float(s or 0) for _, s in sig}) < 5:
        continue  # 占位期
    p0_all = closes_on(sd)
    px = [closes_on(tdays[tidx[sd] + h]) for h in range(H + 1)]
    # 市场基准路径（等权，剔bad）
    uni = [t for t in p0_all if p0_all[t] > 0 and t[:6] not in bad]
    ok = all(t in px[h] and px[h][t] > 0 for t in uni for h in range(H + 1))
    mkt = []
    for h in range(H + 1):
        mkt.append(np.mean([(px[h][t] / p0_all[t] - 1) * 100 for t in uni if t in px[h] and px[h][t] > 0]))
    data = []
    for code, cs in sig:
        ts = code + ('.SH' if code.startswith(('6', '9')) else '.SZ')
        if ts in p0_all and p0_all[ts] > 0 and code not in bad and all(ts in px[h] and px[h][ts] > 0 for h in range(H + 1)):
            data.append((float(cs or 0), ts))
    if len(data) < 100:
        continue
    data.sort()
    n = len(data)
    groups = {'D1': [t for _, t in data[:n // 10]],
              'D10': [t for _, t in data[9 * n // 10:]],
              'NEG': [t for _, t in data[:100]]}
    days_used += 1
    for gname, g in groups.items():
        for h in range(H + 1):
            r = np.mean([(px[h][t] / p0_all[t] - 1) * 100 for t in g])
            paths[gname].append((h, r - mkt[h]))
    for h in range(H + 1):
        mkt_path[h].append(mkt[h])

print(f'信号日数={days_used}  (超额=组等权收益-全市场等权, 同日起点)')
print('H=持有交易日  市场基准累计= ' + " ".join(f"{np.mean(mkt_path[h]):+5.1f}" for h in [1,2,3,5,7,10,13,16,20]))
for gname in ('D1', 'NEG', 'D10'):
    col = {h: [] for h in range(H + 1)}
    for h, v in paths[gname]:
        col[h].append(v)
    hs = [1, 2, 3, 5, 7, 10, 13, 16, 20]
    vals = [np.mean(col[h]) for h in hs]
    # 首次转正日
    first_pos = next((h for h in range(1, 21) if np.mean(col[h]) > 0), None)
    worst = min(np.mean(col[h]) for h in range(1, 21))
    print(f'{gname:3s} 逐日超额%: ' + " ".join(f"D{h}={v:+5.2f}" for h, v in zip(hs, vals)) +
          f"  | 首个转正日=H{first_pos} 路径最深超额={worst:+.2f}")