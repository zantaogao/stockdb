#!/usr/bin/env python3
"""修复5/25剩余26只异常股票"""
import duckdb
from pathlib import Path

DB = Path.home() / '.hermes' / 'stockdb' / 'stock.db'
conn = duckdb.connect(str(DB))

# 查异常
rows = conn.execute("""
    SELECT stock_code, close, volume, amount, 
           ROUND(amount / (close * volume), 2) as ck
    FROM stock_daily WHERE date='2026-05-25'
    AND volume > 0 AND amount IS NOT NULL
    AND ABS(amount / (close * volume) - 100) > 20
    ORDER BY volume DESC
""").fetchall()

print(f'5/25 量纲异常 {len(rows)} 只:')
for r in rows:
    # check≈1 说明volume是股(应除以100), check≈0.01说明volume是万股(应除以10000)
    if 0.5 < r[4] < 2:
        fix = '股→手(/100)'
    elif r[4] < 0.1:
        fix = '万股→手(/10000?)'
    else:
        fix = f'unknown(ck={r[4]})'
    print(f'  {r[0]} close={r[1]:.2f} vol={r[2]:>12,} amt={r[3]:>14,.0f} ck={r[4]:.4f} → {fix}')

# 修复：check≈1的volume/100, check≈0.01的volume/10000
fixed = 0
for r in rows:
    code = r[0]
    ck = r[4]
    if 0.5 < ck < 2:
        conn.execute(f"UPDATE stock_daily SET volume = volume / 100 WHERE stock_code='{code}' AND date='2026-05-25'")
        fixed += 1
    elif ck < 0.1:
        conn.execute(f"UPDATE stock_daily SET volume = volume / 10000 WHERE stock_code='{code}' AND date='2026-05-25'")
        fixed += 1

conn.commit()
print(f'\n修复 {fixed} 只')

# 最终验证
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
