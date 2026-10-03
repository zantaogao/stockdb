import sqlite3
c = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
try:
    print('fusion_3f_signals max date:', c.execute("select max(trade_date), count(*) from fusion_3f_signals where trade_date>='20260929'").fetchall())
except Exception as e:
    # try duckdb-style or other table name
    tabs = [r[0] for r in c.execute("select name from sqlite_master where type='table'").fetchall()]
    print('tables:', tabs[:30])
