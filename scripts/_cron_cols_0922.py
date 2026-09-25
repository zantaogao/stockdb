# -*- coding: utf-8 -*-
import duckdb, sqlite3, os, json
os.chdir('/Users/zantao/.hermes/stockdb')
c = duckdb.connect('tushare.db', read_only=True)
for t in ['sw_daily_raw','stock_industry_raw','index_daily_raw','daily','stock_basic']:
    try: print(t, [r[1] for r in c.execute(f'DESCRIBE {t}').fetchall()])
    except Exception as e: print(t, 'ERR', e)
