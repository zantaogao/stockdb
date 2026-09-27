# v7 质量体检: 稳健IC口径(Newey-West t、按月/分年、剔除妖股单日主导) 2026-09-26
import json, numpy as np, pandas as pd
from pathlib import Path
from scipy import stats
import lightgbm as lgb
B = Path.home()/'.hermes/stockdb/analysis/retrain_20260926'
df = pd.read_parquet(B/'samples_40d_v7.parquet'); df['date'] = df['date'].astype(str)
model = lgb.Booster(model_str=(B/'lgb_reg_40d_v7.txt').read_text())
sd = json.load(open(B/'v40_v7_stats.json'))
feats = ['f%d'%j for j in range(26)] + ['f31','f32','f33','f34']
dts = np.sort(df['date'].unique()); split = dts[int(len(dts)*0.8)]
va = df[df['date'] >= split].reset_index(drop=True)
X = np.column_stack([(np.clip(va[f].to_numpy(float), sd[f'feat_{j}']['low'], sd[f'feat_{j}']['high'])
    - sd[f'feat_{j}']['mean'])/sd[f'feat_{j}']['std'] for j, f in enumerate(feats)])
X = np.nan_to_num(X, nan=0.0); pred = model.predict(X)
y = va['y40'].to_numpy(float); d = va['date'].to_numpy()
rows = []
for dd in np.unique(d):
    m = d == dd
    if m.sum() < 200: continue
    ics.append if False else None
    rho = stats.spearmanr(pred[m], y[m])[0]
    # 剔妖版: 当日剔 |y|>P99.5
    yy = y[m]; cut = np.percentile(yy, 99.5)
    keep = yy <= cut
    rho_c = stats.spearmanr(pred[m][keep], yy[keep])[0] if keep.sum() >= 200 else np.nan
    rows.append((dd, rho, rho_c))
r = pd.DataFrame(rows, columns=['date','rho','rho_trim'])
r['month'] = r['date'].str[:4] + '-' + r['date'].str[4:6]
r = r.dropna(subset=['rho'])
def nw_t(x, L=12):
    x = np.asarray(x, float); n = len(x); xm = x.mean()
    g = np.var(x - xm)
    for l in range(1, L+1):
        g += 2*(1-l/(L+1))*np.mean((x[l:]-xm)*(x[:-l]-xm))
    return xm/np.sqrt(g/n)
print(f"全样本日均IC {r.rho.mean():+.4f} NW-t={nw_t(r.rho):.2f} 正占比{(r.rho>0).mean()*100:.0f}% n={len(r)}天")
print(f"剔妖版日均IC {r.rho_trim.mean():+.4f} NW-t={nw_t(r.rho_trim):.2f} 正占比{(r.rho_trim>0).mean()*100:.0f}%")
print("分年:")
for yr, g in r.groupby(r.date.str[:4]):
    print(f"  {yr}: 日均IC {g.rho.mean():+.4f} 正占比{(g.rho>0).mean()*100:.0f}% {len(g)}天")
mon = r.groupby('month').rho.mean()
print(f"月度最差3: " + ', '.join(f'{k}:{v:+.3f}' for k,v in mon.nsmallest(3).items()))
print(f"月度最好3: " + ', '.join(f'{k}:{v:+.3f}' for k,v in mon.nlargest(3).items()))
# top10% 组合等权收益 vs 全市场基准（钱能不能赚到）
va2 = va.assign(pred=pred); top = va2.groupby('date').apply(lambda g: g.nlargest(20, 'pred').y40.mean(), include_groups=False)
base = va.groupby('date').y40.mean()
ex = top - base
print(f"每日Top20等权 y40 均值 {top.mean():+.2f}% vs 基准 {base.mean():+.2f}% → 超额 {ex.mean():+.2f}% NW-t={nw_t(ex):.2f}")
