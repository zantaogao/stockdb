"""特征截面 RankIC 审计 v3 — 10d/20d/40d 样本全维正确命名 + 兜底维甄别。
输出 analysis/feat_ic_audit_0926/v3_{10d,20d,40d}_month_mean.csv + v3_recent_summary.csv
"""
import duckdb, numpy as np, pandas as pd, os
from scipy import stats

BASE = os.path.expanduser('~/.hermes/stockdb')
PV_INDICES = [0,1,2,3,5,6,7,10,11,12,13,14,15,16,17,18,19,23,24,25,26,27,28,29,30,32,33,34,35,36,37]
B = ['chg5','chg10','chg20','chg60','chg120','d5','d10','d20','d60','d120','bull1','bull2',
     'rr','std20','vr','pos','nh','vpc','c1d','c3d','ep','bp','ln_cap','ex5','ex10','ex20',
     'skew20','kurt20','dn_streak','up_ratio10','vol_chg','rel_str','kurt60','slope5','slope10',
     'accel','vp_shrink','vp_div']
NAMES31 = [B[i] for i in PV_INDICES]
BASE_KEEP = [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,18,19,20,21,22,23,24,25,26,28,29]
NAMES40 = [B[i] for i in BASE_KEEP] + ['kdj_k','cci','rsi_12']
OUT = f'{BASE}/analysis/feat_ic_audit_0926'

con = duckdb.connect()
summ_frames = []
for tag, ycol, names in [('10d','y10',NAMES31), ('20d','y20',NAMES31), ('40d','y40',NAMES40)]:
    nf = len(names)
    cols = ['date'] + [f'f{j}' for j in range(nf)] + [ycol]
    df = con.execute(f"select {','.join(cols)} from read_parquet('{BASE}/analysis/retrain_20260926/samples_{tag}.parquet')").df()
    rows = []
    for d, g in df.groupby('date'):
        if len(g) < 500: continue
        y = g[ycol].to_numpy()
        rec = {'date': str(d)}
        for j in range(nf):
            x = g[f'f{j}'].to_numpy()
            mask = np.isfinite(x) & np.isfinite(y)
            if mask.sum() < 500 or np.unique(x[mask]).size < 10:
                rec[names[j]] = np.nan   # 死维/常数维
            else:
                rec[names[j]] = stats.spearmanr(x[mask], y[mask])[0]
        rows.append(rec)
    ic = pd.DataFrame(rows); ic['ym'] = ic['date'].str[:6]
    ic.to_csv(f'{OUT}/v3_{tag}_per_day.csv', index=False)
    ic.groupby('ym')[names].mean().to_csv(f'{OUT}/v3_{tag}_month_mean.csv')
    recent = ic[ic['date'] >= '20250901']
    s = []
    for n in names:
        v = recent[n].dropna()
        if len(v) == 0:
            s.append({'model': tag, 'feat': n, 'status': 'DEAD(常数/兜底)', '近12月IC': np.nan, 'p': np.nan, 'n': 0})
        else:
            t, p = stats.ttest_1samp(v, 0)
            s.append({'model': tag, 'feat': n, 'status': 'ok', '近12月IC': round(float(v.mean()),4),
                      'p': round(float(p),4), 'n': len(v)})
    summ_frames.append(pd.DataFrame(s))
    print(f'{tag}: {len(ic)} 天 IC 已存', flush=True)
    del df, ic

s = pd.concat(summ_frames)
s.to_csv(f'{OUT}/v3_recent_summary.csv', index=False)
pd.set_option('display.width', 200)
print('=== 近12月(20250901~) 单特征日均截面RankIC（按|IC|排）===')
for tag in ['10d','20d','40d']:
    sub = s[s.model==tag].dropna(subset=['近12月IC']).reindex(
        s[s.model==tag].dropna(subset=['近12月IC'])['近12月IC'].abs().sort_values(ascending=False).index)
    dead = s[(s.model==tag) & (s.status!='ok')]['feat'].tolist()
    print(f'--- {tag} 死维: {dead}')
    print(sub[['feat','近12月IC','p','n']].head(15).to_string(index=False))
con.close()
