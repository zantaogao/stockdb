#!/usr/bin/env python3
"""只读探针4：未来数日除权 ∩ 持仓（评估紧迫性，不写任何库）"""
import sqlite3, sys, importlib.util
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location('aca', BASE / 'scripts/adjust_corporate_action.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import tushare as ts
ts.set_token(m.CONFIG.get('tushare_token', ''))
pro = ts.pro_api()

c = sqlite3.connect(str(BASE / 'ledger.db'))
codes = {str(r[0]) for r in c.execute("SELECT code FROM holdings WHERE status='hold'")}
codes |= {str(r[0]) for r in c.execute("SELECT code FROM strategy_positions")}
c.close()

for day in ['20260917', '20260918', '20260921', '20260922']:
    try:
        divs = m.get_ex_divs(pro, day)
    except Exception as e:
        print(day, 'API err', e); continue
    hit = set(divs) & codes
    print(f'{day}: 全市场 {len(divs)} 只除权，命中持仓 {sorted(hit) if hit else "无"}')
