import duckdb, sys, json, os
from collections import Counter

for f in ["/Users/zantao/.hermes/stockdb/tushare.db.wal", "/Users/zantao/.hermes/stockdb/tushare.db.shm"]:
    if os.path.exists(f):
        try: os.remove(f)
        except: pass

conn = db.get_tushare_db()

results = conn.execute("""
    SELECT date, type, code, name, score, time
    FROM signal_history 
    WHERE date >= '2026-07-10'
    ORDER BY time DESC
""").fetchall()

print("Total 2026-07-10 records:", len(results))

type_counts = Counter(r[1] for r in results)
print("\nBy type:")
for t, c in type_counts.most_common():
    print(f"  {t}: {c}")

# 列出所有记录（最多50条）
for row in results[:50]:
    dt = str(row[0])
    tm = str(row[5])[:19] if row[5] else ""
    tp = str(row[1])
    sc = row[4]
    co = row[2]
    nm = row[3]
    print(f"  {tm} | type={tp:<20} | score={str(sc):>7} | code={co} | name={nm}")

conn.close()
