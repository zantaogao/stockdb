#!/usr/bin/env python3
"""Check which stocks still need backfill (regular stocks that missed first run)"""
import duckdb, os, sys
sys.stdout.reconfigure(line_buffering=True)

DB_PATH = os.path.expanduser("~/.hermes/stockdb/stock.db")
conn = duckdb.connect(DB_PATH, read_only=True)

# Stocks that have <200 days and earliest data is >= 2025-11-01
# These are regular stocks that weren't covered in the first backfill pass
rows = conn.execute("""
    SELECT stock_code, MIN(date) as first, COUNT(*) as days
    FROM stock_daily 
    GROUP BY stock_code
    HAVING days < 200 AND first >= DATE '2025-11-01'
    ORDER BY first
""").fetchall()

print(f"第一批未覆盖（需backfill）: {len(rows)} 只")
reg = [r for r in rows if r[0][0] in ('0','3','6') and r[0][:2] not in ('68','92','00','30')]
print(f"其中普通A股: {len(reg)} 只")
for r in rows:
    print(f"  {r[0]}: {r[2]}天 (最早{r[1]})")

conn.close()
