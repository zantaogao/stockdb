import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
print('defense_state:', con.execute('select * from defense_state').fetchall())
print('balance:', con.execute('select cash_balance, total_value, last_update from account_balance').fetchall())
print('holdings n:', con.execute("select count(*), sum(shares*latest_price) from holdings where status='hold'").fetchall())
print('watchlist bought recent:', con.execute("select ts_code,status,scan_date from watchlist where status='bought' order by scan_date desc limit 5").fetchall())
