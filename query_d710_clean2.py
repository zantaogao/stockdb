import duckdb, os

for f in ["/Users/zantao/.hermes/stockdb/tushare.db.wal", "/Users/zantao/.hermes/stockdb/tushare.db.shm"]:
    if os.path.exists(f):
        try: os.remove(f)
        except: pass

conn = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)

results = conn.execute("""
    SELECT date, stock_code, stock_name, fusion_score, reg_pred, final_score, industry
    FROM signal_history 
    WHERE date >= '2026-07-10'
    ORDER BY date DESC, final_score DESC
""").fetchall()

print("Today's signal_history records ({}):".format(len(results)))
for row in results:
    dt = str(row[0])
    print(f"  {dt} | code={row[1]:<8} | name={str(row[2]):<6} | fusion={row[3] if row[3] else 'N/A':>7} | reg_pred={row[4] if row[4] is not None else 'N/A':>7} | final_score={row[5] if row[5] is not None else 'N/A':>7} | industry={row[6]}")

# 检查这些记录是什么时候写入的——看有没有time或created_at字段
schema = conn.execute("PRAGMA table_info(signal_history)").fetchall()
print("\nFull schema:")
for c in schema:
    print(f"  col={c[1]}, type={c[2]}")

conn.close()
