import sqlite3
BASE = '/Users/zantao/.hermes/stockdb/'
s = sqlite3.connect(BASE + 'ledger.db')
rows = s.execute("SELECT trade_date, trade_time, direction, code, quantity, amount FROM trade_log WHERE strategy='agent_auto' AND trade_date='2026-09-28' ORDER BY trade_time").fetchall()
nb = sum(1 for r in rows if r[2] == 'BUY')
buys = sum(r[5] for r in rows if r[2] == 'BUY')
print('today rows:', len(rows), 'orders_left:', 5 - len(rows), 'buy_left:', 300000 - buys)
for r in rows:
    print(r)
t = sqlite3.connect(BASE + 'tushare.db')
for c in ['003027.SZ','300970.SZ','300982.SZ','301276.SZ','603382.SH','301167.SZ','001238.SZ','300837.SZ']:
    r = t.execute("SELECT trade_date, close, pct_chg FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", (c,)).fetchone()
    print(c, r)
