# -*- coding: utf-8 -*-
import duckdb, os
os.chdir('/Users/zantao/.hermes/stockdb')
c = duckdb.connect('tushare.db', read_only=True)
print('board_daily cols:', [r for r in c.execute('DESCRIBE board_daily').fetchall()])
print(c.execute('SELECT * FROM board_daily ORDER BY trade_date DESC LIMIT 3').fetchall())
print('stock_info cols:', [r[1] for r in c.execute('DESCRIBE stock_info').fetchall()])
