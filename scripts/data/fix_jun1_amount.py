#!/usr/bin/env python3
"""定点修复 stock_daily 数据"""
import duckdb
from pathlib import Path

DB = Path.home() / '.hermes' / 'stockdb' / 'stock.db'
conn = duckdb.connect(str(DB))

# 6/1: volume存的是股(Sina K线API), 修正为手, 同时补amount
r = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE date='2026-06-01' AND amount IS NULL").fetchone()
print(f'6/1 amount为NULL: {r[0]} 条')
conn.execute("""
    UPDATE stock_daily 
    SET amount = ROUND(CAST(volume AS DOUBLE) * close, 2),
        volume = volume / 100
    WHERE date = '2026-06-01' AND amount IS NULL
""")
conn.commit()
r2 = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE date='2026-06-01' AND amount IS NULL").fetchone()
print(f'6/1修复后 amount为NULL: {r2[0]} 条')

# 验证
print('\n最终验证:')
for d in ['2026-05-25','2026-05-29','2026-06-01','2026-06-04','2026-06-05','2026-06-08']:
    r = conn.execute(f"""
        SELECT COUNT(*),
               SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END),
               SUM(CASE WHEN amount IS NOT NULL AND volume > 0 
                        AND ABS(amount / (close * volume) - 100) > 20 THEN 1 ELSE 0 END)
        FROM stock_daily WHERE date='{d}'
    """).fetchone()
    ok = '✅' if r[1]==0 and r[2]==0 else f'❌(amt_null={r[1]}, unit_wrong={r[2]})'
    print(f'  {d}  cnt={r[0]:>5}  {ok}')

conn.close()
