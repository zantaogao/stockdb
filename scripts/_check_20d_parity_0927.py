# 生产 score_stock 20d 分 与 训练样本真值 y20 同分布对账:
# 从 20d 样本 parquet 抽一天(20260827)，用样本行 f0..f30 直接推理得"样本口径20d分"，
# 与生产 score_stock(as_of=20260827) 的 reg20_pred 逐票对比。若逐列一致则 Spearman≈1。
import sys, json, sqlite3
import numpy as np, pandas as pd, duckdb, lightgbm as lgb
from scipy import stats
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')

BASE='/Users/zantao/.hermes/stockdb'
m = lgb.Booster(model_file=f'{BASE}/models/lgb_reg_20d_v2.txt')
st = json.load(open(f'{BASE}/models/v20_v2_stats.json'))

# 1) 样本口径: 20260827 全部票 f0..f30 → 标准化 → predict
df = pd.read_parquet(f'{BASE}/analysis/retrain_20260926/samples_20d.parquet', columns=['code']+[f'f{i}' for i in range(31)]+[ 'date'])
df = df[df['date']=='20260827']
print('样本口径 20260827 票数:', len(df))
X = df[[f'f{i}' for i in range(31)]].values.astype(np.float64)
# 与生产 _standardize 同参: clip(low,high) 后再 zscore
Xn = X.copy()
for j in range(31):
    s = st[f'feat_{j}']
    if s['std']>0:
        Xn[:,j] = np.clip(Xn[:,j], s['low'], s['high'])
        Xn[:,j] = (Xn[:,j]-s['mean'])/s['std']
Xn = np.nan_to_num(Xn, nan=0.0)
df['score_sample'] = m.predict(Xn)

# 2) 生产口径 score_stock（含特征重算路径）
from core.scoring import score_stock, _safe_connect
conn=_safe_connect()
sample = df[['code','score_sample']].sample(n=min(300,len(df)), random_state=1)
pairs=[]
for code, ss in sample.itertuples(index=False):
    c = code.split('.')[0]
    r = score_stock(c, conn=conn, as_of_date='20260827')
    if r and r['reg_pred'] not in (None,0):
        pairs.append((c, ss, r['reg_pred']))
conn.close()
# 剔除 tushare 因子表缺行(旧无_bfq表日期)的票——生产置0、样本行非0，属双轨数据缺失非口径错
import tushare as ts_mod  # placeholder not used
keep=[p for p in pairs if abs(p[2])>1e-12]
print(f'剔除生产因子缺行(分=0): {len(pairs)-len(keep)} 票')
pairs=keep
a=np.array([p[1] for p in pairs]); b=np.array([p[2] for p in pairs])
rho=stats.spearmanr(a,b)[0]
print(f'对账 n={len(pairs)} Spearman(样本口径, 生产score_stock) = {rho:.4f}')
print('maxdiff:', np.abs(a-b).max(), ' 一致(<0.05):', (np.abs(a-b)<0.05).mean())
