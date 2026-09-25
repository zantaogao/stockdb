#!/usr/bin/env python3
"""简版验证: features.py 38维输出是否正确"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent.parent))
import duckdb
import numpy as np
from core.features import compute_raw_features

BASE=Path.home()/'.hermes'/'stockdb'
conn=duckdb.connect(str(BASE/'stock.db'),read_only=True)

codes=['000001','600519','300750','000002']
names=['chg5','chg10','chg20','chg60','chg120',
       'd5','d10','d20','d60','d120',
       'bull1','bull2','rr','std20','vr','pos',
       'nh','vpc','c1d','c3d','ep','bp','ln_cap',
       'ex5','ex10','ex20',
       'skew20','kurt20','dn_streak','up_ratio10','vol_chg','rel_str',
       'kurt60','slope5','slope10','accel','vp_shrink','vp_div']

for code in codes:
    rows=conn.execute(f"SELECT date,close,open,high,low,change_pct,volume,amount FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 200").fetchall()
    feat,dt=compute_raw_features(code,rows,conn)
    if feat is None:
        print(f"{code}: ❌ None");continue
    print(f"\n{code} ({dt})  len={len(feat)}")
    for i in range(0,38,6):
        line=''
        for j in range(i,min(i+6,38)):
            line+=f'{names[j]:>12}:{feat[j]:>8.4f} '
        print(line)

    # 验证关键特征合理性
    print('  →',end=' ')
    checks=[]
    if abs(feat[0])<0.2:checks.append('chg5✓')
    if abs(feat[5])<0.2:checks.append('d5✓')
    if 0<feat[12]<100:checks.append('rr✓')
    if -0.5<feat[26]<0.5:checks.append('skew20✓')
    if 1<feat[27]<10:checks.append('kurt20✓')
    if 0<=feat[28]<=20:checks.append('dn_streak✓')
    if 0<=feat[29]<=1:checks.append('up_ratio10✓')
    print(' '.join(checks) if checks else '⚠部分异常')

conn.close()
print("\n✅ 验证完成")
