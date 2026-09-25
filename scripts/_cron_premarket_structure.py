#!/usr/bin/env python3
"""盘前补充：A股自身结构（中证1000/上证/创业板 均线与20日高低位置）+ 主账户卖出敞口折算"""
import sys, io
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import duckdb

con = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
print('### 指数结构（index_daily_raw）###')
for tc, nm in [('000852.SH', '中证1000'), ('000001.SH', '上证指数'), ('399006.SZ', '创业板指'), ('000300.SH', '沪深300')]:
    try:
        rows = con.execute("SELECT trade_date, close FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 25", [tc]).fetchall()
        if not rows:
            print(f'  {nm}: 未获取(无数据)'); continue
        rows = rows[::-1]
        cl = [float(r[1]) for r in rows]; dt = [str(r[0]) for r in rows]
        last = cl[-1]
        ma5 = sum(cl[-5:]) / 5; ma10 = sum(cl[-10:]) / 10; ma20 = sum(cl[-20:]) / 20
        hi20 = max(cl[-20:]); lo20 = min(cl[-20:])
        # 近5日逐日涨跌
        pcts = [f"{dt[i][4:]}:{(cl[i]/cl[i-1]-1)*100:+.2f}%" for i in range(len(cl) - 5, len(cl))]
        print(f"  {nm}: 收{last:.2f} [{dt[-1]}]  MA5 {ma5:.2f}({(last/ma5-1)*100:+.2f}%) MA10 {ma10:.2f}({(last/ma10-1)*100:+.2f}%) MA20 {ma20:.2f}({(last/ma20-1)*100:+.2f}%)")
        print(f"      距20日高 {hi20:.2f} → {(last/hi20-1)*100:+.2f}%   距20日低 {lo20:.2f} → {(last/lo20-1)*100:+.2f}%")
        print(f"      近5日: {' '.join(pcts)}")
    except Exception as e:
        print(f'  {nm}: 未获取({type(e).__name__}: {str(e)[:60]})')

print()
print('### 主账户卖出敞口折算（收盘价×股数）###')
import sqlite3
c = sqlite3.connect(str(BASE / 'ledger.db'))
TOTAL = 1145240
items = [('301557', '常友科技', 100, 80.82, '规则5C 无条件清仓(fusion-2.5 & 持仓≥30交易日)'),
         ('002454', '松芝股份', 3600, 4.90, '回撤止盈线 仅高0.1%（需大盘≤-2%）'),
         ('688636', '智明达', 100, 19.74, '回撤止盈线 高0.9%（需大盘≤-2%）'),
         ('300658', '延江股份', 2800, 9.85, 'R4止损线(成本×0.94=9.616) 距+2.4%'),
         ('605598', '上海港湾', 3300, 24.33, 'R4止损线(持仓止损23.70) 距+2.7%')]
tot = 0
for code, nm, sh, px, why in items:
    amt = sh * px; tot += amt
    print(f'  {nm} {code}: {sh}股 × {px} = {amt:,.0f}元 = 总资产{amt/TOTAL*100:.1f}%  ← {why}')
print(f'  合计敞口 {tot:,.0f}元 = 总资产{tot/TOTAL*100:.1f}%')
print(f'  其中今日大概率真触发: 常友科技 8,082元 = 0.7%')
print(f'  其中依赖大盘≤-2%才触发: 松芝+智明达 19,614元 = 1.7%')
print(f'  其中依赖盘中止损价被击穿: 延江+上海港湾 107,869元 = 9.4%')

print()
print('### 策略账户 R7 浮亏止损（现价≤成本×0.94）贴身票 ###')
rows = c.execute("SELECT account_id, stock_code, stock_name, cost_price, current_price, shares FROM strategy_holdings").fetchall()
for aid, code, nm, cp, px, sh in rows:
    if cp and px and px <= cp * 0.955:
        print(f'  [{aid}] {nm} {code}: 成本{cp} 现价{px} = {(px/cp-1)*100:+.1f}%  市值{px*sh:,.0f}')
