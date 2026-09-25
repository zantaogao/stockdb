#!/usr/bin/env python3
"""09-07 补跑: 手动更新在 fin_balancesheet 被看门狗杀,活库已交换到0907。
直接调 update_tushare_api 里的剩余6个表函数(各函数自带续传:从库里最新日期接着拉)。"""
import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('uta', '/Users/zantao/.hermes/stockdb/scripts/update_tushare_api.py')
uta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uta)   # import 时不跑 main (有 __main__ 保护)

pro = uta.get_pro()
for fn in ('update_fin_balancesheet', 'update_fin_cashflow',
           'update_stk_limit', 'update_moneyflow',
           'update_stk_factor_pro', 'update_stk_factor'):
    print(f'\n##### {fn} #####', flush=True)
    getattr(uta, fn)(pro)
print('ALL_DONE', flush=True)