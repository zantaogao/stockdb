#!/usr/bin/env python3
"""09-11 验证 daily_report.py 新增 10d独立榜（复刻段逻辑，is_bad 用原函数口径）。"""
import sqlite3, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
state = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
d3 = '20260910'

# 与 daily_report.py 同源：sb 来自 get_st_names()
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('dr', '/Users/zantao/.hermes/stockdb/scripts/daily_report.py')
# 不整跑 main，只借 get_st_names/is_bad：用 exec 摘函数源码
src = open('/Users/zantao/.hermes/stockdb/scripts/daily_report.py').read()
import re
ns = {'sqlite3': sqlite3, 'sys': sys}
for fn in ['get_st_names', 'is_bad']:
    m = re.search(rf"def {fn}\(.*?(?=\ndef )", src, re.S)
    exec(m.group(0), ns)
sb = ns['get_st_names']()
is_bad = ns['is_bad']

_r10 = state.execute("""
    SELECT stock_code, stock_name, reg10 FROM signal_history
    WHERE REPLACE(date,'-','')=? AND reg10 IS NOT NULL
    ORDER BY reg10 DESC LIMIT 50
""", (d3,)).fetchall()
_fus_top10 = {r[0] for r in state.execute("""
    SELECT stock_code FROM signal_history
    WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
    ORDER BY fusion_score DESC LIMIT 10
""", (d3,)).fetchall()}
print(f"=== 10d独立榜（{d3}）===")
added = 0
for r in _r10:
    if is_bad(sb, r[0]):
        continue
    star = '★' if r[0] in _fus_top10 else ''
    print(f"    {added+1}. {star}{r[0]} {r[1] or ''} 10d预测{r[2]*100:+.1f}%")
    added += 1
    if added >= 10:
        break
