import duckdb
from datetime import date
c = duckdb.connect('state.db')
today = date.today().isoformat()
print(f"检查日期：{today}")
result = c.execute(f"SELECT COUNT(*) FROM signal_history WHERE date='{today}'").fetchone()[0]
print(f"今日记录数：{result}")
if result > 0:
    rows = c.execute(f"SELECT stock_code, stock_name, fusion_score FROM signal_history WHERE date='{today}' ORDER BY fusion_score DESC LIMIT 10").fetchall()
    print("\nTop 10 股票:")
    for r in rows:
        print(f"  {r[0]} {r[1]} {r[2]}")
