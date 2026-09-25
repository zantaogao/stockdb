import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('ledger.db', timeout=10)
c.execute("ATTACH DATABASE 'signals.db' AS sig")
print('sig tables like stock_basic:', c.execute("SELECT name FROM sig.sqlite_master WHERE name LIKE '%stock_basic%'").fetchall())
print('ledger tables like stock_basic:', c.execute("SELECT name FROM main.sqlite_master WHERE name LIKE '%stock_basic%'").fetchall())
for q, label in [
    ("SELECT industry FROM sig.stock_basic WHERE stock_code='300986'", 'sig.stock_basic stock_code'),
    ("SELECT stock_code, industry FROM sig.stock_basic LIMIT 3", 'sig.stock_basic sample'),
]:
    try:
        print(label, '->', c.execute(q).fetchall())
    except Exception as e:
        print(label, 'ERR:', e)
# also check tushare.db stock_basic for the codes
try:
    import duckdb
    d = duckdb.connect('tushare.db', read_only=True)
    print('tushare 300986:', d.execute("SELECT ts_code, industry FROM stock_basic WHERE ts_code LIKE '300986%'").fetchall())
    print('tushare industry ZZZ count:', d.execute("SELECT COUNT(*) FROM stock_basic WHERE industry IS NULL OR industry=''").fetchone())
    d.close()
except Exception as e:
    print('tushare ERR:', e)