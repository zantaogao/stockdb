#!/usr/bin/env python3
"""只读探针2：除权表新鲜度 + 今日/近日除权 ∩ 持仓（不写任何库）"""
import sqlite3, sys
BASE = '/Users/zantao/.hermes/stockdb'

codes = set()
c = sqlite3.connect(f'{BASE}/ledger.db')
tbls = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
codes |= {str(r[0]) for r in c.execute("SELECT code FROM holdings")}
codes |= {str(r[0]) for r in c.execute("SELECT code FROM strategy_positions")}
c.close()
print('持仓代码数:', len(codes))

import duckdb
d = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
for tt, codecol, excol in [('dividend','ts_code','ex_date'), ('adjustment_factors','stock_code','ex_date')]:
    print(f'\n== {tt} (code={codecol}, ex={excol}) ==')
    for day in ['20260916','20260915','20260914','20260911']:
        rows = [r[0] for r in d.execute(f"SELECT DISTINCT {codecol} FROM {tt} WHERE {excol}=?", [day]).fetchall()]
        cs = {str(x).split('.')[0] for x in rows}
        hit = cs & codes
        print(f'  {day}: {len(cs)} 只  交集={sorted(hit) if hit else "无"}')
    print('  最新 ex_date 前5:', [str(r[0]) for r in d.execute(f"SELECT DISTINCT {excol} FROM {tt} WHERE {excol} IS NOT NULL ORDER BY {excol} DESC LIMIT 5").fetchall()])

# 今日实时价对比（判断持仓是否有价格断层/停牌）
print('\n== 持仓最新行情 ==')
print('  daily max:', d.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])
d.close()
