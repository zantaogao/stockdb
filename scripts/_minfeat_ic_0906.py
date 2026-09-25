# f47-f56 日内微观特征 IC 筛选（2026-09-06）
# 样本限定重叠段 >=2025-04-08；bench=31维标准因子整体（线性回归取残差）；报告原始RankIC + 残差RankIC 分年t值
import numpy as np, pandas as pd
from scipy import stats

BASE = '/Users/zantao/.hermes/stockdb'
sm = pd.read_parquet(BASE + '/analysis/retrain_10d_v4/samples_v4c.parquet')
mf = pd.read_parquet(BASE + '/analysis/retrain_10d_v4/_min_feats.parquet')
sm['date'] = sm['date'].astype(str)
df = sm.merge(mf, on=['date','code'], how='inner')
print('重叠样本:', len(df), df['date'].min(), '~', df['date'].max(), '| 特征覆盖率:', df['f47'].notna().mean())

BENCH = [f'f{i}' for i in range(31)]
FEATS = [f'f{i}' for i in range(47, 57)]
df['year'] = df['date'].str[:4]

def daily_ic(g, col, resid_of=None):
    """按日横截面 Spearman IC；resid_of=DataFrame列名列表时先做日内OLS残差"""
    out = []
    for dt, d in g:
        if len(d) < 200: continue
        y = d['y'].values
        ok = np.isfinite(y)
        if resid_of is not None:
            X = d[resid_of].values.astype(float)
            ok &= np.isfinite(X).all(axis=1)
            if ok.sum() < 200: continue
            X_ = np.column_stack([np.ones(ok.sum()), X[ok]])
            # 秩变换后回归（对厚尾稳健）
            yr = stats.rankdata(y[ok]); Xr = np.column_stack([np.ones(ok.sum())] + [stats.rankdata(X[ok][:, j]) for j in range(X.shape[1])])
            try:
                beta, *_ = np.linalg.lstsq(Xr, yr, rcond=None)
                y = yr - Xr @ beta
            except Exception:
                continue
            x = d[col].values[ok]
            good = np.isfinite(x)
            if good.sum() < 200: continue
            ic = stats.spearmanr(x[good], y[good]).statistic
        else:
            x = d[col].values[ok]
            good = np.isfinite(x)
            if good.sum() < 200: continue
            ic = stats.spearmanr(x[good], y[good]).statistic
        if np.isfinite(ic): out.append((dt, ic))
    return pd.DataFrame(out, columns=['date','ic'])

rows = []
for col in FEATS:
    for kind, resid in [('raw', None), ('resid31', BENCH)]:
        ics = daily_ic(df.groupby('date'), col, resid)
        ics['year'] = ics['date'].str[:4]
        row = {'feat': col, 'kind': kind, 'IC均值': round(ics['ic'].mean(), 4)}
        for y_ in sorted(ics['year'].unique()):
            s = ics[ics['year'] == y_]['ic']
            row[y_] = f"{s.mean():+.4f}/t{s.mean()/(s.std()/np.sqrt(len(s))):+.1f}"
        rows.append(row)
res = pd.DataFrame(rows)
print(res.to_string(index=False))
res.to_csv(BASE + '/analysis/minfeat_ic_0906.csv', index=False)
print('→ analysis/minfeat_ic_0906.csv')