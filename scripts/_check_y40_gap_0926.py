# 病根定位：y40 是否缺持有期连续性约束（停牌复牌跳变污染）2026-09-26
from pathlib import Path
import numpy as np, pandas as pd
B = Path.home()/'.hermes/stockdb/analysis/retrain_20260926'
df = pd.read_parquet(B/'samples_40d_v7.parquet'); df['date'] = df['date'].astype(str)
dts = sorted(df['date'].unique()); split = dts[int(len(dts)*0.8)]
big = df[(df['date'] >= split) & (df['y40'] > 100)].sort_values('y40', ascending=False).head(5)
cal = {d: i for i, d in enumerate(dts)}
for _, r in big.iterrows():
    sub = df[df['code'] == r['code']].sort_values('date')
    gaps = [(a, b, cal[b] - cal[a]) for a, b in zip(sub['date'][:-1], sub['date'][1:]) if cal[b] - cal[a] > 45]
    print(f"{r['code']} y40={r['y40']:.0f}% @{r['date']}: 样本日历断点(>45日)数={len(gaps)} 样例={gaps[:2]}")
