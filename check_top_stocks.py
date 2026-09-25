#!/usr/bin/env python3
import duckdb

conn = duckdb.connect('/Users/zantao/.hermes/stockdb/state.db')

latest_date = conn.execute('SELECT MAX(date) FROM signal_history').fetchone()[0]

print(f"=== Top 20 股票 (日期={latest_date}) ===")
print("排名 | 代码        | 名称      | reg10_pred | reg20   | reg40   | 融合评分")
print("-" * 90)

top20 = conn.execute(f"""
    SELECT stock_code, stock_name, reg10_pred, reg20, reg40, final_score
    FROM signal_history
    WHERE date = '{latest_date}'
    ORDER BY final_score DESC
    LIMIT 20
""").fetchall()

for i, r in enumerate(top20, 1):
    reg10_str = "{:.2f}".format(r[2]) if r[2] is not None else "None"
    name = (r[1] or "")[:10]
    print("{:4} | {:10} | {:10} | {:10} | {:7.2f} | {:7.2f} | {:7.2f}".format(
        i, r[0], name, reg10_str, r[3], r[4], r[5]))

null_count = conn.execute("SELECT COUNT(*) FROM signal_history WHERE date='{}' AND reg10_pred IS NULL".format(latest_date)).fetchone()[0]
total = conn.execute("SELECT COUNT(*) FROM signal_history WHERE date='{}'".format(latest_date)).fetchone()[0]
print("\nreg10_pred 为 NULL: {}/{} ({:.1f}%)".format(null_count, total, 100*null_count/total))

conn.close()
