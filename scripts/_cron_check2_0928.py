import sqlite3, json
BASE = '/Users/zantao/.hermes/stockdb/'
t = sqlite3.connect(BASE + 'minutes/5min/minutes.duckdb') if False else None
# candidates' prev close from tushare.db (duckdb?)
try:
    s = sqlite3.connect(BASE + 'tushare.db')
    print('tushare is sqlite ok')
except Exception as e:
    print('tushare err', e)
import os
print(os.path.getsize(BASE + 'tushare.db'))
with open(BASE + 'tushare.db', 'rb') as f:
    print(f.read(16))
