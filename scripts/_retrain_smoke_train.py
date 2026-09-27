# 冒烟：小样本快训，验证 PC 训练管线（与 train.py 同代码路径）
import os
os.environ.setdefault('RETRAIN_DIR', os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('RETRAIN_ONLY', '10d')
import train as T

_orig = T.train_one
def smoke(tag, parquet, ycol, feats_n, model_name, stats_name, ic_name, params_):
    _orig(tag, parquet, ycol, feats_n,
          'smoke_' + model_name, 'smoke_' + stats_name, 'smoke_' + ic_name, params_)
    # 覆盖 parquet 为小样本
T.train_one = lambda *a, **k: None  # 防 main 自动跑

import pandas as pd, numpy as np, json, time
BASE = T.BASE

def run_smoke(tag, parquet, ycol, feats_n):
    df = pd.read_parquet(BASE / parquet)
    df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
    dates = np.sort(df['date'].unique())
    lo, hi = dates[int(len(dates)*0.78)], dates[int(len(dates)*0.98)]
    sm = df[(df['date'] >= lo) & (df['date'] <= hi)]
    sm = sm[sm['date'].isin(dates[int(len(dates)*0.78):int(len(dates)*0.98)][::20])]
    sm.to_parquet(BASE / f'_smoke_{parquet}', index=False)
    print(f'[smoke-{tag}] 冒烟样本 {len(sm):,} 行 范围 {sm.date.min()}~{sm.date.max()}', flush=True)
    _orig(tag, f'_smoke_{parquet}', ycol, feats_n,
          f'smoke_{tag}.txt', f'smoke_{tag}_stats.json', f'smoke_{tag}_ic.csv',
          dict(T.params, _max_rounds=200, _es=50))

run_smoke('smoke10', 'samples_10d.parquet', 'y10', 31)
print('SMOKE_DONE', flush=True)
