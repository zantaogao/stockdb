#!/usr/bin/env python3
"""80档内二次排序键证据：cmmr_score>=80 的票，档内按 fusion_score(三模型融合原始分)
排序是否有区分度。对成熟信号日（未来20个交易日已齐）：把 80/100 档票按 fusion_score
中位数劈成两半，各扣当日全市场等权，看 20d 超额差。>=3 个成熟日给出方向。"""
import sqlite3, duckdb, numpy as np
from pathlib import Path
BASE = Path.home() / '.hermes' / 'stockdb'
state = sqlite3.connect(str(BASE / 'signals.db'))
tushare = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)

def ts(c):
    c = str(c)
    return f'{c}.SH' if c.startswith(('6', '68', '9')) else f'{c}.SZ'

dates = [r[0] for r in state.execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
hi_rows_all, lo_rows_all = [], []
for d in dates:
    avail = tushare.execute(
        "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?", (d,)).fetchone()[0]
    if avail < 20:
        continue
    nd = tushare.execute(
        "SELECT MAX(trade_date) FROM (SELECT DISTINCT trade_date FROM daily WHERE trade_date > ? ORDER BY trade_date ASC LIMIT 20)",
        (d,)).fetchone()[0]
    rows = state.execute("""
        SELECT stock_code, cmmr_score, fusion_score FROM signal_history
        WHERE REPLACE(date,'-','')=? AND cmmr_score >= 80
    """, (d,)).fetchall()
    if len(rows) < 20:
        continue
    codes = {ts(r[0]): r[0] for r in rows}
    ph = ','.join(['?'] * len(codes))
    p0 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", (d,) + tuple(codes)).fetchall()}
    p20 = {r[0]: float(r[1]) for r in tushare.execute(
        f"SELECT ts_code, close FROM (SELECT ts_code, close, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date) rn FROM daily WHERE trade_date > ? AND trade_date <= ? AND ts_code IN ({ph})) WHERE rn=20",
        (d, nd) + tuple(codes)).fetchall()}
    # 全市场等权
    m0 = tushare.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", (d,)).fetchall()
    m1 = tushare.execute("SELECT ts_code, close FROM (SELECT ts_code, close, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date) rn FROM daily WHERE trade_date > ? AND trade_date <= ?) WHERE rn=20", (d, nd)).fetchall()
    m0d = {r[0]: float(r[1]) for r in m0}
    m1d = {r[0]: float(r[1]) for r in m1}
    mret = [(m1d[k] / m0d[k] - 1) * 100 for k in m0d if k in m1d and m0d[k] > 0]
    mkt = float(np.mean(mret)) if mret else 0.0
    items = []
    for code, cs, fs in rows:
        t = ts(code)
        if t in p0 and t in p20 and p0[t] > 0:
            items.append(((p20[t] / p0[t] - 1) * 100 - mkt, float(fs or 0)))
    if len(items) < 20:
        continue
    items.sort(key=lambda x: x[1])
    mid = len(items) // 2
    lo = [x[0] for x in items[:mid]]
    hi = [x[0] for x in items[mid:]]
    hi_rows_all.append((d, len(items), float(np.mean(hi)), float(np.mean(lo)), float(np.mean(hi)) - float(np.mean(lo))))
    print(f"{d} n={len(items):4d} 档内fusion高半超额={np.mean(hi):+.2f}% 低半={np.mean(lo):+.2f}% 差={np.mean(hi)-np.mean(lo):+.2f}pp")

if hi_rows_all:
    diffs = [r[4] for r in hi_rows_all]
    wins = sum(1 for x in diffs if x > 0)
    print(f"\n成熟日 {len(diffs)} 个，高半跑赢低半 {wins}/{len(diffs)} 天，日均差 {np.mean(diffs):+.2f}pp")
state.close(); tushare.close()
