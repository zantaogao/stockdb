# -*- coding: utf-8 -*-
"""持仓真实收盘价 + 风控距离复算（2026-09-15）"""
import duckdb, sqlite3, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
lc.row_factory = sqlite3.Row
TODAY = '20260915'

codes = [r['code'] for r in lc.execute("SELECT code FROM holdings WHERE status='hold'").fetchall()]
ts = [c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ') for c in codes]
q = ','.join('?' * len(ts))
px = {}
for tc, d, o, h, l, c, pc, p in con.execute(f"""SELECT ts_code, trade_date, open, high, low, close, pre_close, pct_chg
        FROM daily WHERE ts_code IN ({q}) AND trade_date >= '20260901' ORDER BY trade_date""", ts).fetchall():
    px.setdefault(str(tc).split('.')[0], {})[str(d)] = (float(o), float(h), float(l), float(c), float(p), float(pc))

prev_days = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 1", (TODAY,)).fetchall()]
prev = prev_days[0]
print(f"上一交易日 = {prev}")
print(f"{'代码':<8}{'名称':<9}{'持仓价':>8}{'真实收':>8}{'今涨%':>7}{'成本':>8}{'止损':>8}{'距止损%':>9}{'目标':>8}{'距目标%':>9}{'峰值':>8}{'距峰值%':>9}")
tot_val = 0
for r in lc.execute("SELECT * FROM holdings WHERE status='hold'").fetchall():
    c0 = r['code']
    d = px.get(c0, {}).get(TODAY)
    if not d:
        print(f"{c0} 无今日行情")
        continue
    o, h, l, c, p, pc = d
    pk = lc.execute("SELECT peak_price FROM position_peaks WHERE code=?", (c0,)).fetchone()
    pkv = float(pk[0]) if pk else 0
    sl = float(r['stop_loss'] or 0)
    tp = float(r['target_price'] or 0)
    cost = float(r['avg_cost'] or 0)
    sh = int(r['shares'] or 0)
    tot_val += c * sh
    dsl = (c / sl - 1) * 100 if sl else None
    dtp = (tp / c - 1) * 100 if tp else None
    dpk = (c / pkv - 1) * 100 if pkv else None
    print(f"{c0:<8}{r['name']:<9}{float(r['latest_price'] or 0):>8.2f}{c:>8.2f}{p:>+7.2f}{cost:>8.2f}{sl:>8.2f}"
          f"{(dsl if dsl is not None else float('nan')):>9.1f}{(tp):>8.2f}{(dtp if dtp is not None else float('nan')):>9.1f}{pkv:>8.2f}"
          f"{(dpk if dpk is not None else float('nan')):>9.1f}  今振幅{(h-l)/pc*100:.1f}%")
print(f"\n持仓市值合计(真实收盘价) = {tot_val:,.0f}")

cb = lc.execute("SELECT * FROM account_balance").fetchall()
print("\naccount_balance:", [tuple(x) for x in cb])

# 主账户总资产核对
print("\n-- 主账户现金/总资产（daily_report 口径）--")
for r in lc.execute("SELECT * FROM account_balance").fetchall():
    print("  ", dict(r))

print("\n-- watchlist 全列 --")
cols = [c[1] for c in lc.execute("PRAGMA table_info(watchlist)").fetchall()]
print("  cols:", cols)
for r in lc.execute("SELECT * FROM watchlist WHERE scan_date >= ? ORDER BY scan_date DESC LIMIT 25", (TODAY,)).fetchall():
    print("  ", dict(r))
con.close(); lc.close()
