#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import duckdb, os, json
tdb = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
top = tdb.execute("""
  WITH agg AS (SELECT b.industry ind, AVG(d.pct_chg) a, COUNT(*) n, SUM(d.amount)/1e5 amt
    FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
    WHERE d.trade_date='20260924' AND b.industry IS NOT NULL AND b.industry!='' GROUP BY 1)
  SELECT ind, ROUND(a,2), n, ROUND(amt,1) FROM agg ORDER BY a DESC LIMIT 10""").fetchall()
bot = tdb.execute("""
  WITH agg AS (SELECT b.industry ind, AVG(d.pct_chg) a, COUNT(*) n
    FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
    WHERE d.trade_date='20260924' AND b.industry IS NOT NULL AND b.industry!='' GROUP BY 1)
  SELECT ind, ROUND(a,2), n FROM agg ORDER BY a ASC LIMIT 10""").fetchall()
print('TOP'); [print(x) for x in top]
print('BOT'); [print(x) for x in bot]
# 林业成分
print('林业成分:', tdb.execute("""SELECT d.ts_code,b.name,ROUND(d.pct_chg,2) FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
 WHERE d.trade_date='20260924' AND b.industry='林业'""").fetchall())
print('公路成分:', tdb.execute("""SELECT d.ts_code,b.name,ROUND(d.pct_chg,2) FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
 WHERE d.trade_date='20260924' AND b.industry='公路' ORDER BY d.pct_chg DESC LIMIT 6""").fetchall())
tdb.close()
