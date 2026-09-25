import duckdb
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
try:
    print(db.execute("SELECT table_name FROM duckdb_tables() WHERE table_name LIKE '%sw%' OR table_name LIKE '%industr%'").fetchall())
except Exception as e:
    print('ERR', e)
try:
    print(db.execute("SELECT database_name, table_name FROM duckdb_tables() WHERE table_name='sw_daily_raw'").fetchall())
except Exception as e:
    print('ERR2', e)
