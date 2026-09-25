#!/usr/bin/env python3
"""独立复算 ic_window 7/24 fwd10_top_3f（不走 ic_window.py 代码）2026-08-08"""
import sqlite3, duckdb

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'

s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

sd = '20260724'

# 1. bad_codes（ST/北交所）——复现 ic_window.py 逻辑（state.db 的 stock_basic）
bad = set()
for r in s.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    sc, nm, mk = r[0], r[1] or '', r[2] or ''
    if ('ST' in nm or '退' in nm) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))

# 2. 7/24 强买集合
rows = s.execute("SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? AND signal='强买' AND fusion_3f_score IS NOT NULL", (sd,)).fetchall()
print(f"7/24 强买总数: {len(rows)} (signal='强买')")
# 全市场对比
alln = s.execute("SELECT COUNT(*), SUM(CASE WHEN signal='强买' THEN 1 ELSE 0 END) FROM fusion_3f_signals WHERE REPLACE(date,'-','')=?", (sd,)).fetchone()
print(f"7/24 fusion_3f_signals 总 {alln[0]} 行, 强买 {alln[1]} ({alln[1]/alln[0]*100:.1f}%)  ← 正常应~15%")

# 3. 过滤 bad + 排序取前 10
cand = [(c, sc) for c, sc, _ in rows if c not in bad]
cand.sort(key=lambda x: x[1], reverse=True)
top10 = cand[:10]
print(f"\n强买(滤ST/北交所后) {len(cand)} 只, Top10:")
for i, (c, sc) in enumerate(top10, 1):
    print(f"  {i}. {c} score={sc}")

# 4. 10 日收益：7/24 -> 信号日后第 10 个交易日
tds = [r[0] for r in t.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
i0 = tds.index(sd)
end = tds[i0 + 10]
print(f"\n窗口: {sd} -> {end} (第10个交易日)")
rets = []
for c, _ in top10:
    ts = f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ"
    r0 = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (sd, ts)).fetchone()
    rn = t.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (end, ts)).fetchone()
    if r0 and rn and r0[0] and rn[0]:
        ret = (float(rn[0]) / float(r0[0]) - 1) * 100
        rets.append(ret)
        print(f"  {c}: {r0[0]} -> {rn[0]} = {ret:+.2f}%")
    else:
        print(f"  {c}: 价格缺失 {ts}")
if rets:
    print(f"\n等权 10 日收益: {sum(rets)/len(rets):+.3f}% (n={len(rets)})")
    print(f"ic_window 表值: +11.216%")

# 5. 7/30 大跌日这 10 只的表现
print(f"\n7/30 大跌日这 10 只表现 (7/29 -> 7/30):")
for c, _ in top10:
    ts = f"{c}.SH" if c.startswith(('6','68','9')) else f"{c}.SZ"
    r1 = t.execute("SELECT close FROM daily WHERE trade_date='20260729' AND ts_code=?", (ts,)).fetchone()
    r2 = t.execute("SELECT close FROM daily WHERE trade_date='20260730' AND ts_code=?", (ts,)).fetchone()
    if r1 and r2 and r1[0] and r2[0]:
        print(f"  {c}: {(float(r2[0])/float(r1[0])-1)*100:+.2f}%")
    else:
        print(f"  {c}: 缺数据")
t.close(); s.close()
