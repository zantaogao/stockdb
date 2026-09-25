#!/usr/bin/env python3
"""补查 state.db 三因子表 + 特征维度 2026-08-08"""
import sqlite3, sys

STATE = '/Users/zantao/.hermes/stockdb/state.db'
s = sqlite3.connect(STATE)

print("=" * 60)
print("1) state.db 中的三因子表")
for t in ['new_factors','flow_alpha','vol_adj']:
    try:
        cols = s.execute(f"PRAGMA table_info({t})").fetchall()
        n = s.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        d = s.execute(f"SELECT MAX(REPLACE(date,'-','')) FROM {t}").fetchone()[0]
        print(f"   {t}: {len(cols)} 列 {[c[1] for c in cols]}, {n} 行, 最新日 {d}")
    except Exception as e:
        print(f"   {t}: {e}")

print("=" * 60)
print("2) 特征维度来源")
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
import inspect
try:
    import feat_tushare
    src = inspect.getsource(feat_tushare.compute_features)
    # 找 return 数组长度
    import re
    m = re.findall(r'np\.array\(\[([^\]]*)\]\)', src)
    print(f"   feat_tushare.compute_features return 数组元素数: {[len(x.split(',')) for x in m] if m else '未找到'}")
    # 找特征名列表定义
    for name in dir(feat_tushare):
        if 'FEAT' in name.upper() or 'INDEX' in name.upper() or 'COL' in name.upper():
            v = getattr(feat_tushare, name)
            if isinstance(v, (list, tuple)):
                print(f"   {name}: {len(v)} 项")
except Exception as e:
    print(f"   feat_tushare: {e}")

# PV_INDICES 在训练脚本
import glob, os
for f in glob.glob('/Users/zantao/.hermes/stockdb/train_*.py') + glob.glob('/Users/zantao/.hermes/stockdb/*train*.py'):
    try:
        src = open(f).read()
        m = re.search(r'PV_INDICES\s*=\s*\[([^\]]*)\]', src)
        if m:
            print(f"   {os.path.basename(f)}: PV_INDICES = {len(m.group(1).split(','))} 维")
    except Exception:
        pass

s.close()
