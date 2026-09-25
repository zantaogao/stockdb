#!/usr/bin/env python3
"""查询ETF表现"""
import duckdb, sys
from pathlib import Path

db = duckdb.connect(str(Path.home() / '.hermes/stockdb/fund.db'), read_only=True)

# ETF分类
keywords = ['沪深300','中证500','科创50','创业板','半导体','芯片','AI','人工智能','红利','中概','恒生','纳斯达克','标普','消费','医药','证券','银行','新能源','光伏','白酒','军工','黄金','国债']
print('=== ETF分类列表 ===')
for kw in keywords:
    count = db.execute(f"SELECT COUNT(*) FROM etf_info WHERE fund_name LIKE '%{kw}%'").fetchone()[0]
    if count > 0:
        names = db.execute(f"SELECT fund_code, fund_name FROM etf_info WHERE fund_name LIKE '%{kw}%' ORDER BY fund_size DESC LIMIT 3").fetchall()
        print(f'\n{kw}({count}只):')
        for n in names:
            sz = db.execute(f"SELECT fund_size FROM etf_info WHERE fund_code='{n[0]}'").fetchone()
            size_str = f"{sz[0]/100000000:.0f}亿" if sz and sz[0] else "?"
            print(f'  {n[0]} {n[1]} ({size_str})')

# 近期表现TOP
print('\n=== 近30日涨幅TOP15 ETF ===')
top = db.execute("""
    WITH priced AS (
        SELECT fund_code, date, price,
            FIRST_VALUE(price) OVER (PARTITION BY fund_code ORDER BY date DESC ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) as old_price,
            ROW_NUMBER() OVER (PARTITION BY fund_code ORDER BY date DESC) rn
        FROM etf_daily WHERE date >= '2026-04-01'
    )
    SELECT DISTINCT p.fund_code, i.fund_name,
        ROUND((p.price / p.old_price - 1) * 100, 2) as chg,
        ROUND(i.fund_size / 100000000, 1) as size_yi
    FROM priced p JOIN etf_info i ON p.fund_code = i.fund_code
    WHERE p.old_price > 0 AND p.price > 0 AND i.fund_size > 500000000
    ORDER BY chg DESC LIMIT 15
""").fetchall()
for t in top:
    print(f'  {t[0]} {t[1]:20s} {t[2]:+.2f}% 规模{t[3]:.0f}亿')

# 宽基指数ETF表现
print('\n=== 主流宽基ETF表现 ===')
main_etfs = [('510300','沪深300'),('510500','中证500'),('510050','上证50'),('159915','创业板'),('588000','科创50'),('159949','创业板50')]
for code, name in main_etfs:
    r = db.execute(f"""
        SELECT price, date FROM etf_daily WHERE fund_code='{code}'
        ORDER BY date DESC LIMIT 1
    """).fetchone()
    r30 = db.execute(f"""
        SELECT price FROM etd_daily WHERE fund_code='{code}'
        ORDER BY date DESC LIMIT 30,1
    """).fetchone()
    if r and r30:
        chg = (r[0]/r30[0]-1)*100
        print(f'  {code} {name}: {r[0]:.3f} ({chg:+.2f}%)')
    else:
        print(f'  {code} {name}: 无数据')

db.close()
