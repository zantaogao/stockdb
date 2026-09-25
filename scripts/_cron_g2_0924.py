#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 盘后深复盘 第二轮（板块用 daily join stock_basic.industry；IC序列）"""
import duckdb, sqlite3, json, os
BASE = os.path.expanduser('~/.hermes/stockdb')
out = {}
tdb = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

# 板块近10日：每日 top8 / bot8（等权平均涨幅）
rows = tdb.execute("""
WITH agg AS (
  SELECT d.trade_date, b.industry industry_name, AVG(d.pct_chg) apct, COUNT(*) n
  FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
  WHERE d.trade_date >= '20260910' AND b.industry IS NOT NULL AND b.industry != ''
  GROUP BY d.trade_date, b.industry
)
SELECT trade_date, industry_name, ROUND(apct,2), n FROM agg
QUALIFY ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY apct DESC) <= 8
ORDER BY trade_date, apct DESC
""").fetchall()
out['sw_top_by_day'] = rows

# 板块5日累计（0918-0924 四个交易日累计）与连续强势天数
rows = tdb.execute("""
WITH agg AS (
  SELECT d.trade_date, b.industry industry_name, AVG(d.pct_chg) apct
  FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
  WHERE d.trade_date >= '20260910' AND b.industry IS NOT NULL AND b.industry != ''
  GROUP BY d.trade_date, b.industry
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY apct DESC) rk FROM agg
)
SELECT industry_name,
       ROUND(SUM(CASE WHEN trade_date>='20260918' THEN apct ELSE 0 END),2) cum4,
       ROUND(SUM(apct),2) cum10,
       SUM(CASE WHEN rk<=10 THEN 1 ELSE 0 END) top10days
FROM ranked GROUP BY industry_name ORDER BY cum4 DESC LIMIT 12
""").fetchall()
out['sw_cum'] = rows

# 板块最近一日排名（用于确认今天领跌的制药/铜/黄金是否此前强势）
rows = tdb.execute("""
WITH agg AS (
  SELECT d.trade_date, b.industry industry_name, AVG(d.pct_chg) apct
  FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
  WHERE d.trade_date >= '20260910' AND b.industry IS NOT NULL AND b.industry != ''
  GROUP BY d.trade_date, b.industry
)
SELECT trade_date, industry_name, ROUND(apct,2) FROM agg
WHERE industry_name IN ('生物制药','铜','黄金','化学制药','纺织','水运','港口')
ORDER BY industry_name, trade_date
""").fetchall()
out['sw_watch'] = rows
tdb.close()
print(json.dumps(out, ensure_ascii=False, default=str))
