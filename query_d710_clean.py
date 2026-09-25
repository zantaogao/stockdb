import duckdb, os, json

for f in ["/Users/zantao/.hermes/stockdb/tushare.db.wal", "/Users/zantao/.hermes/stockdb/tushare.db.shm"]:
    if os.path.exists(f):
        try: os.remove(f)
        except: pass

conn = db.get_tushare_db()

# 查signal_history今天的所有记录
results = conn.execute("""
    SELECT date, stock_code, stock_name, fusion_score, reg_pred, final_score, industry
    FROM signal_history 
    WHERE date >= '2026-07-10'
    ORDER BY date DESC
""").fetchall()

print("Total 2026-07-10 records:", len(results))

# Also check what types of data were written by different cron jobs
# Look at daban signals (might be in a different table or have different columns)

# Check board_daily for today
try:
    board = conn.execute("""
        SELECT trade_date, ts_code, name, pct_chg, close_1d 
        FROM board_daily 
        WHERE trade_date >= '2026-07-10' 
        ORDER BY trade_date DESC LIMIT 20
    """).fetchall()
    print(f"\nboard_daily today: {len(board)} records")
except Exception as e:
    print(f"board_daily error: {e}")

# Check if there's a daban table or view
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
daban_tables = [t[0] for t in tables if 'daban' in t[0].lower()]
print(f"\nDaban-related tables: {daban_tables}")

for dt in daban_tables:
    try:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {dt}").fetchone()
        print(f"  {dt}: {cnt[0]} rows")
    except Exception as e2:
        print(f"  {dt}: ERROR - {e2}")

conn.close()
