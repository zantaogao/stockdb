#!/usr/bin/env python3
"""精确复现 ic_window.py 7/24 fwd10_top_3f 的候选构建 2026-08-08"""
import sqlite3, duckdb

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
sd = '20260724'

s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

# bad_codes（state.db stock_basic）
bad = set()
for r in s.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    sc, nm, mk = r[0], r[1] or '', r[2] or ''
    if ('ST' in nm or '退' in nm) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
        bad.add(str(sc))
print(f"bad_codes: {len(bad)} 只")

sig = s.execute(
    "SELECT stock_code, reg10, reg20, reg40, fusion_score, cmmr_score, fusion_score_cmmr FROM signal_history "
    "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
print(f"signal_history 7/24: {len(sig)} 行")

f3f_rows = s.execute(
    "SELECT stock_code, fusion_3f_score, signal FROM fusion_3f_signals "
    "WHERE REPLACE(date,'-','')=? AND fusion_3f_score IS NOT NULL", (sd,)).fetchall()
f3f = {r[0]: r[1] for r in f3f_rows}
f3f_strong = {r[0] for r in f3f_rows if r[2] == '强买'}
print(f"fusion_3f 7/24: {len(f3f_rows)} 行, 强买 {len(f3f_strong)} 只")

tds = [r[0] for r in t.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
i0 = tds.index(sd)
end = tds[i0 + 10]
print(f"窗口 {sd} -> {end}")

def code_to_ts(c):
    return f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"

codes = [code_to_ts(c) for c, *_ in sig]
uniq = list(dict.fromkeys(codes))
ph = ','.join(['?'] * len(uniq))
px = {}
for d in (sd, end):
    for tc, cl in t.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (d,) + tuple(uniq)).fetchall():
        px[(d, tc)] = float(cl)

rec_codes, rets10 = [], []
for row, tc in zip(sig, codes):
    code = row[0]
    p0 = px.get((sd, tc)); pn = px.get((end, tc))
    if not p0 or p0 <= 0 or not pn or pn <= 0:
        continue
    rec_codes.append(code)
    rets10.append((pn / p0 - 1) * 100)
print(f"价格配对成功: {len(rec_codes)} 只")

# top10_ret 复刻: 强买集合内排序取前10（带 code 追踪）
items = []
for code, r in zip(rec_codes, rets10):
    if code in bad:
        continue
    if code not in f3f_strong:
        continue
    items.append((code, f3f.get(code, 0.0), r))
print(f"强买∩signal_history∩有价(滤ST/北交所): {len(items)} 只")
scs = sorted(sc for _, sc, _ in items)
print(f"分数分布: 100分={sum(1 for _,sc,_ in items if sc>=100)}, 90-100分={sum(1 for _,sc,_ in items if 90<=sc<100)}, 中位={scs[len(scs)//2]}")

items.sort(key=lambda x: x[1], reverse=True)
top = items[:10]
print(f"\nTop10（ic_window 口径, 等权 10 日收益）:")
total = 0
for i, (code, sc, r) in enumerate(top, 1):
    total += r
    print(f"  {i}. {code} score={sc} ret={r:+.2f}%")
print(f"\n等权: {total/len(top):+.3f}%   (ic_window 表值: +11.216%)")

# 差异诊断: 我上一版直接取 fusion_3f 强买 top10 与这里的差异
print(f"\n诊断: signal_history 7/24 有 {len(sig)} 行 vs fusion_3f_signals 7/24 {len(f3f_rows)} 行")
sh_codes = {r[0] for r in sig}
only_f3f = [c for c in f3f_strong if c not in sh_codes]
print(f"强买中不在 signal_history 的: {len(only_f3f)} 只 (前10: {only_f3f[:10]})")
t.close(); s.close()
