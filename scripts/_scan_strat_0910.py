import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
rows = c.execute("""SELECT trade_date,strategy,code,name,direction,price,quantity,notes
    FROM trade_log WHERE trade_date IN ('20260910','2026-09-10') ORDER BY id""").fetchall()
print('trades 20260910:', len(rows))
for r in rows: print(r)
print('--- NAV rows 20260910:')
for r in c.execute("SELECT account_id,date,nav,cash,pos_value,daily_ret,n_pos FROM strategy_accounts_legacy WHERE date IN ('20260910','2026-09-10') ORDER BY account_id"):
    print(r)
print('--- positions per strategy account (today buys):')
for r in c.execute("SELECT account_id,code,name,shares,avg_cost,buy_date FROM strategy_positions WHERE buy_date>='2026-09-09' ORDER BY account_id,buy_date"):
    print(r)