import duckdb, sqlite3, os, re
H = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)
tabs = [r[0] for r in t.execute("SHOW TABLES").fetchall()]
sw = [x for x in tabs if 'sw' in x or 'industry' in x or 'ind' in x]
print('ind-related tables:', sw)
print('all tables sample:', tabs[:80])
