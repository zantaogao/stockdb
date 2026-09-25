#!/usr/bin/env python3
"""只读探针3：调 tushare API 查今日除权 ∩ 持仓（不写任何库，复用生产 get_ex_divs）"""
import sqlite3, sys, importlib.util
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))

spec = importlib.util.spec_from_file_location('aca', BASE / 'scripts/adjust_corporate_action.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)   # 仅加载定义，不跑 main()

import tushare as ts
ts.set_token(m.CONFIG.get('tushare_token', ''))
pro = ts.pro_api()

for day in ['20260916', '20260915']:
    divs = m.get_ex_divs(pro, day)
    print(f'{day}: 全市场除权除息 {len(divs)} 只 -> {sorted(divs.keys())}')

c = sqlite3.connect(str(BASE / 'ledger.db'))
codes = {str(r[0]) for r in c.execute("SELECT code FROM holdings WHERE status='hold'")}
print('主账户 hold:', sorted(codes))
strat = {}
for aid, code in c.execute("SELECT account_id, code FROM strategy_positions"):
    strat.setdefault(aid, set()).add(str(code))
for aid, s in strat.items():
    print(f'  策略账户 {aid}: {sorted(s)}')
allc = set(codes) | {x for s in strat.values() for x in s}
c.close()

divs16 = m.get_ex_divs(pro, '20260916')
hit = set(divs16) & allc
print('\n>>> 20260916 除权 ∩ 全部持仓:', sorted(hit) if hit else '无交集（今日无需调账）')
# 已记账的 ca_adjustments（防重复）
import os
print('ledger.db exists:', os.path.exists(BASE / 'ledger.db'))
