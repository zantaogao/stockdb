#!/usr/bin/env python3
"""验证 40d v2 模型：特征重要性（因子是否参与）+ 新旧对比准备"""
import sys, json
from pathlib import Path
import lightgbm as lgb
import numpy as np

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

FEAT_NAMES = [
    'chg5','chg10','chg20','chg60','chg120',
    'd5','d10','d20','d60','d120',
    'bull2','rr','std20','vr','pos',
    'c1d','c3d','ep','bp','ln_cap',
    'ex5','ex10','ex20','skew20','dn_streak','up_ratio10',
    'kdj_k','cci','rsi_12',   # 26/27/28 = 因子
]

m2 = lgb.Booster(model_file=str(BASE / 'models/lgb_reg_40d_mac_v2.txt'))
print(f'v2 模型: {m2.num_trees()} 棵树, {m2.num_feature()} 特征')

imp = m2.feature_importance('gain')
print('\n=== 特征重要性 (gain, 降序) ===')
order = np.argsort(imp)[::-1]
for i in order:
    mark = ' ←因子' if i >= 26 else ''
    print(f'  [{i:2d}] {FEAT_NAMES[i]:<10} {imp[i]:>12.1f}{mark}')

# 因子特征是否有非零重要性
factor_imp = sum(imp[26:29])
total_imp = imp.sum()
print(f'\n3因子重要性合计: {factor_imp:.1f} / {total_imp:.1f} = {factor_imp/total_imp*100:.2f}%')
print('结论:', '✅ 因子参与训练' if factor_imp > 0 else '❌ 因子未参与（全0或未匹配）')

# 旧模型对照
m_old = lgb.Booster(model_file=str(BASE / 'models/lgb_reg_40d_new_stkfactor.txt'))
print(f'\n旧模型: {m_old.num_trees()} 棵树, {m_old.num_feature()} 特征')
imp_old = m_old.feature_importance('gain')
factor_imp_old = sum(imp_old[26:29]) if len(imp_old) >= 29 else 0
print(f'旧模型 3因子重要性: {factor_imp_old:.1f} / {imp_old.sum():.1f} = {factor_imp_old/imp_old.sum()*100:.2f}%')
