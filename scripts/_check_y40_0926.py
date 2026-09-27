# 40d v7 验证段异常归因（2026-09-26）
from pathlib import Path
import numpy as np, pandas as pd
df = pd.read_parquet(Path.home()/'.hermes/stockdb/analysis/retrain_20260926/samples_40d_v7.parquet')
df['date'] = df['date'].astype(str)
dts = np.sort(df['date'].unique()); split = dts[int(len(dts)*0.8)]
va = df[df['date'] >= split]
y = va['y40'].to_numpy(float)
print(f'验证段 {len(va):,} 行 y40: 均值{np.nanmean(y):+.2f} 中位{np.nanmedian(y):+.2f} std={np.nanstd(y):.1f}')
for p in (1,50,90,95,99,99.5,99.9,100):
    print(f'  P{p}: {np.nanpercentile(y,p):+.1f}')
print('y40>100% 行数:', int((y>100).sum()), f'({(y>100).mean()*100:.2f}%)')
print('y40>500% 行数:', int((y>500).sum()), f'({(y>500).mean()*100:.4f}%)')
# 极值行的日期分布（是否集中在早期=退市股复牌尾部）
big = va[y > 100]
print('y40>100% 按年:', big['date'].str[:4].value_counts().to_dict())
