#!/usr/bin/env python3
"""诊断 8/3 reg40 骤降：同股票 as_of=7/31 vs as_of=8/3 的 40d 预测对比"""
import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.scoring import score_stock

codes = ['600508', '301191', '300418', '603186', '000001']
print(f"{'code':<8}{'as_of=7/31 reg40':<18}{'as_of=8/3 reg40':<18}{'差值'}")
for code in codes:
    r1 = score_stock(code, as_of_date='20260731')
    r2 = score_stock(code, as_of_date='20260803')
    a = r1.get('reg40_pred') if r1 else None
    b = r2.get('reg40_pred') if r2 else None
    print(f'{code:<8}{str(a):<18}{str(b):<18}{"-" if a is None or b is None else round(b-a,2)}')
