import sys
sys.path.insert(0, '.')
from core.prices import fetch_prices_batch
import sqlite3, duckdb

cands = ['688275','688063','688191','001332','605598','603863','002595','688155','300905','688355','300984','301233','688390','301512','300935']
px = fetch_prices_batch(cands)
print('LIVE:', px)

# 昨收（最近交易日 pre_close/close）
tdu = duckdb.connect('tushare.db', read_only=True)
rows = tdu.execute("""
SELECT ts_code, trade_date, close FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
  FROM daily WHERE ts_code IN ('688275.SH','688063.SH','688191.SH','001332.SZ','605598.SH','603863.SH','002595.SZ','688155.SH','300905.SZ','688355.SH')
) WHERE rn=1
""").fetchall()
print('LAST_DAILY:', rows)