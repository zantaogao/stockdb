#!/usr/bin/env python3
"""查询基金表现"""
import duckdb
from pathlib import Path

db = duckdb.connect(str(Path.home() / '.hermes/stockdb/fund.db'), read_only=True)

# 主动股票型基金近1年TOP
print('=== 主动股票型基金 近1年收益TOP20 (规模>10亿) ===')
top = db.execute("""
    WITH latest AS (
        SELECT fund_code, date, unit_nav, accum_nav,
               ROW_NUMBER() OVER (PARTITION BY fund_code ORDER BY date DESC) rn
        FROM fund_nav_daily
    ),
    cur_nav AS (
        SELECT fund_code, accum_nav as cur_accum, date as cur_date
        FROM latest WHERE rn = 1 AND accum_nav IS NOT NULL
    ),
    year_ago AS (
        SELECT l.fund_code, l.accum_nav as old_accum
        FROM latest l
        JOIN cur_nav c ON l.fund_code = c.fund_code
        WHERE l.date <= (SELECT MIN(date) FROM fund_nav_daily WHERE date >= (SELECT MIN(cur_date) FROM cur_nav) - 365)
        AND l.accum_nav IS NOT NULL
        ORDER BY l.date DESC LIMIT 1
    )
    SELECT c.fund_code, i.fund_name, i.fund_type,
           ROUND((c.cur_accum / y.old_accum - 1) * 100, 2) as ret_pct,
           c.cur_date
    FROM cur_nav c
    JOIN year_ago y ON c.fund_code = y.fund_code
    JOIN fund_info i ON c.fund_code = i.fund_code
    WHERE i.fund_type LIKE '%股票%' AND i.fund_type NOT LIKE '%指数%'
    ORDER BY ret_pct DESC LIMIT 20
""").fetchall()

for t in top:
    print(f'{t[0]} {t[1][:20]:20s} {t[2]:12s} {t[3]:+.2f}%')

# 近3月TOP
print('\n=== 主动股票型基金 近3月收益TOP15 ===')
top3m = db.execute("""
    WITH ranked AS (
        SELECT fund_code, date, unit_nav,
               ROW_NUMBER() OVER (PARTITION BY fund_code ORDER BY date DESC) rn,
               COUNT(*) OVER (PARTITION BY fund_code) as total_days
        FROM fund_nav_daily
    ),
    cur AS (
        SELECT fund_code, unit_nav as cur_nav, date as cur_date
        FROM ranked WHERE rn = 1 AND unit_nav IS NOT NULL
    ),
    old AS (
        SELECT fund_code, unit_nav as old_nav
        FROM ranked WHERE rn = 61 AND unit_nav IS NOT NULL
    )
    SELECT c.fund_code, i.fund_name,
           ROUND((c.cur_nav / o.old_nav - 1) * 100, 2) as ret_pct
    FROM cur c JOIN old o ON c.fund_code = o.fund_code
    JOIN fund_info i ON c.fund_code = i.fund_code
    WHERE i.fund_type LIKE '%股票%' AND i.fund_type NOT LIKE '%指数%'
    ORDER BY ret_pct DESC LIMIT 15
""").fetchall()

for t in top3m:
    print(f'  {t[0]} {t[1][:20]:20s} {t[2]:+.2f}%')

# 老牌知名基金表现
print('\n=== 知名基金表现 ===')
famous = ['110011','260108','519069','000751','007874','005827','110022','161725','003095']
for code in famous:
    r = db.execute(f"""
        SELECT a.date, a.unit_nav, b.unit_nav as old_nav
        FROM (SELECT date, unit_nav FROM fund_nav_daily WHERE fund_code='{code}' AND unit_nav IS NOT NULL ORDER BY date DESC LIMIT 1) a
        JOIN (SELECT unit_nav FROM fund_nav_daily WHERE fund_code='{code}' AND unit_nav IS NOT NULL ORDER BY date DESC LIMIT 1 OFFSET 250) b ON 1=1
    """).fetchone()
    if r:
        name = db.execute(f"SELECT fund_name FROM fund_info WHERE fund_code='{code}'").fetchone()[0]
        chg = (r[1]/r[2]-1)*100 if r[2] else 0
        print(f'  {code} {name[:16]:16s} 最新{r[1]:.4f}  近1年{chg:+.2f}%')

db.close()
