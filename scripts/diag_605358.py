#!/usr/bin/env python3
"""诊断605358"""
import duckdb, os, sys
sys.path.insert(0, os.path.expanduser("~/.hermes/stockdb/scripts"))
from importlib import util

conn = duckdb.connect(os.path.expanduser("~/.hermes/stockdb/stock.db"))
code = '605358'

info = conn.execute(f"SELECT stock_name, industry, list_date FROM stock_info WHERE stock_code='{code}'").fetchone()
print(f"名称: {info[0]}")
print(f"行业: {info[1]}")
print(f"上市日期: {info[2]}")
print()

rows = conn.execute(f"""
    SELECT date, close, change_pct, amount/1e8, turn_rate, volume
    FROM stock_daily WHERE stock_code='{code}'
    ORDER BY date DESC LIMIT 20
""").fetchall()

print(f"{'日期':<12} {'收盘':>8} {'涨跌':>8} {'成交亿':>7} {'换手':>6}")
print("-" * 45)
for r in rows:
    d, close, chg, amt, tr, vol = r
    print(f"{d}  {close:>8.2f}  {chg:>+7.2f}%  {amt:>6.1f}  {tr:>5.1f}%")

today = "2026-05-20"
close = rows[0][1]

ma5 = conn.execute(f"SELECT AVG(close) FROM stock_daily WHERE stock_code='{code}' AND date >= DATE '{today}' - 5 AND date < '{today}'").fetchone()[0]
ma20 = conn.execute(f"SELECT AVG(close) FROM stock_daily WHERE stock_code='{code}' AND date >= DATE '{today}' - 20 AND date < '{today}'").fetchone()[0]
ma60 = conn.execute(f"SELECT AVG(close) FROM stock_daily WHERE stock_code='{code}' AND date >= DATE '{today}' - 60 AND date < '{today}'").fetchone()[0]

print(f"\n均线:")
print(f"  MA5: {ma5:.2f}  距:{((close-ma5)/ma5*100 if ma5 else 0):+.1f}%")
print(f"  MA20: {ma20:.2f}  距:{((close-ma20)/ma20*100 if ma20 else 0):+.1f}%")
print(f"  MA60: {ma60:.2f}  距:{((close-ma60)/ma60*100 if ma60 else 0):+.1f}%")
above_ma60 = close > ma60 if ma60 else False
print(f"  站上MA60: {above_ma60}")

fin = conn.execute(f"""
    SELECT report_date, roe, revenue_yoy, profit_yoy, gross_margin
    FROM fin_income WHERE stock_code='{code}'
    ORDER BY report_date DESC LIMIT 1
""").fetchone()
if fin:
    print(f"\n财务(最新 {fin[0]}):")
    print(f"  ROE: {fin[1]:.1f}%")
    print(f"  营收增速: {fin[2]:+.1f}%")
    print(f"  利润增速: {fin[3]:+.1f}%")
    print(f"  毛利率: {fin[4]:.1f}%")

val = conn.execute(f"SELECT pe_ttm, pb FROM stock_valuation WHERE stock_code='{code}' ORDER BY date DESC LIMIT 1").fetchone()
if val:
    print(f"\n估值: PE(TTM) {val[0]:.1f}  PB {val[1]:.2f}")

# 长线评分
print()
spec2 = util.spec_from_file_location("scoring", os.path.expanduser("~/.hermes/stockdb/scripts/scoring.py"))
sc = util.module_from_spec(spec2)
spec2.loader.exec_module(sc)
try:
    result = sc.main(code, mode='long')
    if result:
        print(f"长线评分: {result['total']}/100")
        for dim, score in result.get('dimensions', {}).items():
            print(f"  {dim}: {score}")
        if result['total'] >= 60:
            print("  => 合格候选")
        elif result['total'] >= 50:
            print("  => 观察级")
        else:
            print("  => 不参与")
except Exception as e:
    print(f"评分失败: {e}")

# 长线筛选检查（是否在候选池中）
cand = conn.execute(f"""
    SELECT COUNT(*) FROM (
        SELECT t.stock_code FROM stock_daily t
        JOIN stock_info s ON t.stock_code = s.stock_code
        JOIN (SELECT stock_code, AVG(close) as ma60 FROM stock_daily 
              WHERE date >= DATE '{today}'-60 AND date <= '{today}' GROUP BY stock_code) m
          ON t.stock_code = m.stock_code
        LEFT JOIN (SELECT stock_code, roe FROM fin_income
            WHERE (stock_code, report_date) IN (SELECT stock_code, MAX(report_date) FROM fin_income GROUP BY stock_code)
        ) f ON t.stock_code = f.stock_code
        WHERE t.date = '{today}' AND t.close > m.ma60 AND f.roe > 10 AND t.close > 1
          AND t.amount > 1e7 AND LEFT(t.stock_code,3) != '920'
    )
""").fetchone()[0]
print(f"\n长线候选池合格: {'是' if cand > 0 else '否'}")
print(f"  ROE>10: {fin[1] > 10 if fin and fin[1] else False}")
print(f"  站MA60: {above_ma60}")

conn.close()
