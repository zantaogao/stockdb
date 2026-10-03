import duckdb, sqlite3, os
os.chdir('/Users/zantao/.hermes/stockdb')
con = duckdb.connect('tushare.db', read_only=True)
print("stock_info:", [c[0] for c in con.execute("DESCRIBE stock_info").fetchall()])
print(con.execute("SELECT * FROM stock_info LIMIT 3").fetchall())
print("stock_basic:", [c[0] for c in con.execute("DESCRIBE stock_basic").fetchall()])
# check state.db for sw tables
import duckdb as dd
for db in ('state.db','signals.db'):
    try:
        c2 = dd.connect(db, read_only=True)
        tabs=[r[0] for r in c2.execute("SHOW TABLES").fetchall()]
        print(db, [t for t in tabs if 'sw' in t.lower() or 'industr' in t.lower()])
        c2.close()
    except Exception as e:
        print(db, "duckdb ERR", str(e)[:100])
c3 = sqlite3.connect('signals.db')
print("signals.db tables:", [r[0] for r in c3.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() if 'sw' in r[0].lower() or 'industr' in r[0].lower()])
c3.close()
con.close()
