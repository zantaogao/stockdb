#!/usr/bin/env python3
"""只读探针5：09-18/09-21 命中持仓的除权方案明细（评估止损误触发风险）"""
import sys, importlib.util
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location('aca', BASE / 'scripts/adjust_corporate_action.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import tushare as ts
ts.set_token(m.CONFIG.get('tushare_token', ''))
pro = ts.pro_api()
for day, want in [('20260918', ['002972', '603698']), ('20260921', ['300274', '601886'])]:
    divs = m.get_ex_divs(pro, day)
    for c in want:
        print(day, c, divs.get(c))
