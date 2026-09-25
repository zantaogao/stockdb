#!/usr/bin/env python3
"""验证40d脚本特征是否与features.py一致"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent.parent))
import duckdb
import numpy as np
from core.features import compute_raw_features

BASE=Path.home()/'.hermes'/'stockdb'
conn=duckdb.connect(str(BASE/'stock.db'),read_only=True)

codes=['000001','600519']
for code in codes:
    # 从 features.py 取38维
    rows=conn.execute(f"SELECT date,close,open,high,low,change_pct,volume,amount FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 200").fetchall()
    feat,dt=compute_raw_features(code,rows,conn)
    if feat is None:continue
    
    # 40d脚本取前23维（40d用23基础特征，无超额收益）
    feat23=feat[:23]
    
    print(f"\n{code} {dt} — 40d用前23维:")
    names=['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120',
           'bull1','bull2','rr','std20','vr','pos','nh','vpc','c1d','c3d','ep','bp','ln_cap']
    for i,v in enumerate(feat23):
        print(f"  [{i:2d}] {names[i]:>8} = {v:+.6f}")
    
    # 检查合理性
    print('  →',end=' ')
    ok=True
    if abs(feat23[0])>0.2:print(f'chg5异常({feat23[0]:.2f})',end=' ');ok=False
    if feat23[12]<0 or feat23[12]>100:print(f'rr异常({feat23[12]:.1f})',end=' ');ok=False
    if feat23[15]<0 or feat23[15]>100:print(f'pos异常({feat23[15]:.1f})',end=' ');ok=False
    if abs(feat23[18])>0.2:print(f'c1d异常({feat23[18]:.2f})',end=' ');ok=False
    if ok:print('前23维全部合理 ✓')
    
    # 对比40d脚本（SQL）12维 vs features.py对应位置
    # features.py: 0=chg5,1=chg10,2=chg20,3=chg60,4=chg120
    # 5=d5,6=d10,7=d20,8=d60,9=d120
    # 10=bull1,11=bull2,18=c1d,19=c3d
    # SQL输出（40d脚本用120天窗口，features.py用~200行）：应该接近但可能由于窗口差异略有不同
    sql_rows=conn.execute(f"""
        SELECT
            (s.close/LAG(s.close,5)OVER w-1)chg5,
            (s.close/LAG(s.close,10)OVER w-1)chg10,
            (s.close/LAG(s.close,20)OVER w-1)chg20,
            (s.close/LAG(s.close,60)OVER w-1)chg60,
            (s.close/FIRST_VALUE(s.close)OVER w-1)chg120,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)-1)d5,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)-1)d10,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)-1)d20,
            (s.close/AVG(s.close)OVER(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)-1)d60,
            (s.close/AVG(s.close)OVER w-1)d120,
            COALESCE(s.change_pct,0)/100 c1d,
            (s.close/LAG(s.close,3)OVER w-1)c3d
        FROM stock_daily s WHERE s.stock_code='{code}'
        WINDOW w AS(PARTITION BY s.stock_code ORDER BY s.date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW)
        ORDER BY s.date DESC LIMIT 1
    """).fetchone()
    if sql_rows:
        print(f'\n  SQL vs features.py 关键位置对比:')
        sql_mask=[0,1,2,3,4,5,6,7,8,9,10,11,18,19]
        sql_names=['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120','bull1','bull2','c1d','c3d']
        # SQL第10/11是bull1/bull2，手工算
        d5=sql_rows[5];d10=sql_rows[6];d20=sql_rows[7];d60=sql_rows[8]
        sql_b1=1 if d5>d10>d20 else 0;sql_b2=1 if d20>d60 else 0
        sql_vals=[sql_rows[0],sql_rows[1],sql_rows[2],sql_rows[3],sql_rows[4],
                  sql_rows[5],sql_rows[6],sql_rows[7],sql_rows[8],sql_rows[9],
                  float(sql_b1),float(sql_b2),sql_rows[10],sql_rows[11]]
        diff_count=0
        for i,(si,nm) in enumerate(zip(sql_mask,sql_names)):
            v_sql=sql_vals[i];v_feat=feat[si]
            diff=abs(v_sql-v_feat)
            if diff>0.01 and max(abs(v_sql),abs(v_feat))>0.001:
                diff_count+=1
                print(f'    {nm:>8}: SQL={v_sql:+.4f} feat={v_feat:+.4f} diff={diff:.4f}')
        if diff_count==0:
            print(f'    ✅ 全部一致 (微小差异<0.01)')

conn.close()
print("\n✅ 40d验证完成")
