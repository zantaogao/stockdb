#!/usr/bin/env python3
"""只读探针：2026-09-16 除权股 ∩ 持仓（不写任何库）"""
import sqlite3, os, sys

BASE = '/Users/zantao/.hermes/stockdb'
today = '20260916'

# 1) 持仓代码
codes = set()
c = sqlite3.connect(f'{BASE}/ledger.db')
tbls = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if 'holdings' in tbls:
    codes |= {str(r[0]) for r in c.execute("SELECT code FROM holdings")}
if 'strategy_positions' in tbls:
    codes |= {str(r[0]) for r in c.execute("SELECT code FROM strategy_positions")}
print('持仓代码数:', len(codes), sorted(codes))
c.close()

# 2) 今日除权股（tushare.db 只读）
try:
    import duckdb
except Exception as e:
    print('no duckdb in this interpreter:', e); sys.exit(0)
d = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
t = [r[0] for r in d.execute("SELECT table_name FROM information_schema.tables").fetchall()]
div_tbls = [x for x in t if 'div' in x.lower() or 'adj' in x.lower()]
print('候选除权相关表:', div_tbls)
for tt in div_tbls:
    cols = [r[1] for r in d.execute(f"PRAGMA table_info('{tt}')").fetchall()]
    print(f'-- {tt} cols:', cols[:25])
    excols = [x for x in cols if 'ex_date' in x.lower()]
    if not excols:
        continue
    ex = excols[0]
    rows = d.execute(f"SELECT DISTINCT ts_code FROM {tt} WHERE {ex} = ?", [today]).fetchall()
    exs = {str(r[0]).split('.')[0] for r in rows}
    print(f'{tt} {ex}={today} 除权/除息 {len(exs)} 只:', sorted(exs))
    hit = exs & codes
    print(f'>>> 与持仓交集: {sorted(hit) if hit else "无"}')
d.close()
