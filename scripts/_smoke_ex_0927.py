# 冒烟: 3票抽样行, 验证新ex算式命中且非平凡 (recompute_ex只扫单票, 单次调用)
import sys, pandas as pd, numpy as np
sys.path.insert(0,'/Users/zantao/.hermes/stockdb/scripts')
src=open('/Users/zantao/.hermes/stockdb/scripts/_cron_retrain_ex10d_v6_0927.py').read().split("t0=time.time()")[0]
exec(src)
S=SAMPLES[SAMPLES['code'].isin(['000001','300581'])]
# 每票抽3行(早/中/晚各1)
for c,g in S.groupby('code'):
    exd=recompute_ex(c)
    picks=g.iloc[[0, len(g)//2, len(g)-1]]
    for idx,row in picks.iterrows():
        v=exd.get(row['date'])
        print(c, row['date'], 'old ex:', [round(float(x),4) for x in row[['f23','f24','f25']]],
              'new ex:', None if v is None else [round(x,4) for x in v], flush=True)
