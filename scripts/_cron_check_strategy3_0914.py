import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db')
print('=== trades on 20260914 ===')
for r in c.execute("""SELECT * FROM trade_log WHERE REPLACE(trade_date,'-','')='20260914' ORDER BY id""").fetchall():
    print(r)
print('=== last 15 trades ===')
for r in c.execute("""SELECT * FROM trade_log ORDER BY id DESC LIMIT 15""").fetchall():
    print(r)
print('=== 300299 in strategy_positions? ===')
print(c.execute("SELECT * FROM strategy_positions WHERE code LIKE '%300299%'").fetchall())
print('=== fusion_center positions ===')
print(c.execute("SELECT COUNT(*), SUM(shares), SUM(total_cost) FROM strategy_positions WHERE account_id='fusion_center'").fetchone())
print('=== agent_auto positions ===')
for r in c.execute("SELECT * FROM strategy_positions WHERE account_id='agent_auto'").fetchall():
    print(r)
print('=== crash state ===')
for r in c.execute("SELECT * FROM strategy_crash_state ORDER BY crash_date DESC LIMIT 5").fetchall():
    print(r)
