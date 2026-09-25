import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
for tid in ['agent_auto', 'center_dual']:
    print(tid, c.execute("SELECT trade_time, direction, code, name, quantity, price, amount, notes FROM trade_log WHERE strategy=? AND trade_date>='2026-09-24' ORDER BY rowid", (tid,)).fetchall())
