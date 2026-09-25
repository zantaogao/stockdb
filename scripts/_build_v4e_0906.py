# v4e 样本合并（Mac, 2026-09-06）：samples_v4c + _uncon_feats(f39等5维) + _min_feats(f50/f51/f52/f53)
# 输出到 PC 搬运目录，保持 v4d 同字段口径
import pandas as pd, os
BASE = os.path.expanduser('~/.hermes/stockdb')
sm = pd.read_parquet(BASE + '/analysis/retrain_10d_v4/samples_v4c.parquet')
uf = pd.read_parquet(BASE + '/analysis/retrain_10d_v4/_uncon_feats.parquet').rename(columns={'symbol': 'code'})
mf = pd.read_parquet(BASE + '/analysis/retrain_10d_v4/_min_feats.parquet')
mf['date'] = mf['date'].astype(str)
NEW5 = ['f39_vol_diverge', 'f32_zha20', 'f34_overnight_share', 'f43_turn_cv20', 'f44_skew20']
NEW4 = ['f50_intraday_dd', 'f51_vol_burst', 'f52_downside_var', 'f53_kyle_illiq']
m = sm.merge(uf, on=['code', 'date'], how='left')
m = m.merge(mf[['date', 'code', 'f50', 'f51', 'f52', 'f53']].rename(columns=dict(zip(['f50','f51','f52','f53'], NEW4))), on=['code', 'date'], how='left')
assert m[['f34_overnight_share', 'f43_turn_cv20', 'f44_skew20']].notna().mean().min() > 0.9
# f39/f32 是触发子集特征（NaN=未触发，LGBM原生处理），覆盖率低属设计内，只打印不卡
print('样本:', m.shape, '| f50-f53 覆盖:', m[NEW4].notna().mean().round(3).to_dict())
out = BASE + '/pc_export_v4e/'
os.makedirs(out, exist_ok=True)
m.to_parquet(out + 'samples_v4e.parquet', index=False)
print('→', out + 'samples_v4e.parquet')