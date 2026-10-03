"""2026 纯未来段终验（2026-10-02 用户拍板：训19-25，验26）
两臂: A=生产同款29维, D=26基础+mf20(27维). 训练=2019-01~2025-11, 早停集=2025-09~2025-11(训练段尾部,不碰2026), 测试=2026全年(样本至20260730).
注: mf20方向探针窗=2025-01~2026-09, 2025部分进了训练段; 2026段仍与探针尾部重叠约4个月, 非100%闭卷, 结论要带此折扣."""
import os, json, time
import numpy as np, pandas as pd, lightgbm as lgb
from scipy import stats as st
from pathlib import Path
BASE = Path(os.environ.get('MF40_DIR', 'C:/Users/zantan/mf40'))
params = dict(objective='regression', metric='l2', num_leaves=15, learning_rate=0.01,
    feature_fraction=0.6, bagging_fraction=0.6, bagging_freq=5, min_data_in_leaf=300,
    lambda_l1=0.5, lambda_l2=2.0, max_depth=5, min_gain_to_split=0.2, verbose=1, num_threads=8)
FC26 = ['f%d' % j for j in range(26)]
SPLIT_ES, SPLIT_TEST = '20250901', '20260101'

df = pd.read_parquet(BASE / 'samples_40d_mf.parquet')
df['date'] = df['date'].astype(str).str.replace('-', '', regex=False)
tr = df[df.date < SPLIT_ES]; es = df[(df.date >= SPLIT_ES) & (df.date < SPLIT_TEST)]
te = df[df.date >= SPLIT_TEST]
print(f'训练 {len(tr):,} 早停 {len(es):,} 测试 {len(te):,} 测试日 {te.date.nunique()}', flush=True)

def run(tag, feats):
    Xtr, Xes, Xte = (x[feats].to_numpy(float).copy() for x in (tr, es, te))
    for j in range(len(feats)):
        v = Xtr[:, j]; v = v[np.isfinite(v)]
        lo, hi, mu, sd = np.percentile(v, 1), np.percentile(v, 99), float(v.mean()), float(v.std())
        for X in (Xtr, Xes, Xte): X[:, j] = (np.clip(X[:, j], lo, hi) - mu) / sd
    Xtr, Xes, Xte = (np.nan_to_num(x, 0.0) for x in (Xtr, Xes, Xte))
    ytr, yes, yte = (x.y40.to_numpy(float) for x in (tr, es, te))
    t0 = time.time()
    m = lgb.train(params, lgb.Dataset(Xtr, ytr), num_boost_round=2000,
        valid_sets=[lgb.Dataset(Xes, yes)], valid_names=['es'],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(400)])
    pred = m.predict(Xte); dte = te.date.to_numpy()
    recs = [{'date': str(d), 'rank_ic': float(st.spearmanr(pred[dte == d], yte[dte == d])[0])}
            for d in np.unique(dte) if (dte == d).sum() >= 200]
    ics = [r['rank_ic'] for r in recs]
    pd.DataFrame(recs).to_csv(BASE / f'hold26_ic_{tag}.csv', index=False)
    imp = sorted(zip(m.feature_importance('gain'), feats), reverse=True)
    print(f'[{tag}] {time.time()-t0:.0f}s 树{m.num_trees()} 2026日均IC {np.mean(ics):+.4f} n={len(ics)} '
          f'pos {np.mean([i>0 for i in ics])*100:.0f}% top5={[(f, round(g)) for g, f in imp[:5]]}', flush=True)
    return recs

ra = run('A29', FC26 + ['f31', 'f32', 'f33'])
rd = run('D27', FC26 + ['mf20'])
da = {r['date']: r['rank_ic'] for r in ra}; dd = {r['date']: r['rank_ic'] for r in rd}
com = sorted(set(da) & set(dd)); dif = np.array([dd[k] - da[k] for k in com])
def nw_t(x, lag=5):
    n = len(x); xc = x - x.mean(); s0 = (xc * xc).mean()
    lv = max(s0 + 2 * sum((xc[l:] * xc[:-l]).mean() for l in range(1, lag + 1)), s0)
    return x.mean() / np.sqrt(lv / n) if lv > 1e-15 else float('nan')
t = nw_t(dif)
print(f'2026配对: n={len(com)} 日均差 {dif.mean():+.5f} NW-t {t:+.2f} 为正占比 {(dif>0).mean()*100:.0f}%', flush=True)
# 分季度
for q in ['202601', '202602', '202603', '202604', '202605', '202606', '202607']:
    m_ = [i for i, k in enumerate(com) if k.startswith(q)]
    if m_: print(f'  {q}: n={len(m_)} 差 {dif[m_].mean():+.5f}', flush=True)
json.dump(dict(n=len(com), ic_a=float(np.mean([da[k] for k in com])), ic_d=float(np.mean([dd[k] for k in com])),
    mean_diff=float(dif.mean()), nw_t=float(t), pos=float((dif > 0).mean())), open(BASE / 'hold26_cmp.json', 'w'), indent=1)
print('DONE', flush=True)
