import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
# today's CA run log detail
print(con.execute("select * from ca_run_log order by run_date desc limit 3").fetchall())
# what does ca stand for: columns
print([c[1] for c in con.execute('pragma table_info(ca_run_log)')])
print('ca_adjustments recent:', con.execute("select * from ca_adjustments order by rowid desc limit 3").fetchall())
