# c) 残差化十分位：每日截面 OLS 剥 lnmv/mom10/vol20/turn20 后取残差再分组
import duckdb, numpy as np, pandas as pd, os
BASE = os.path.expanduser('~/.hermes/stockdb')
c = duckdb.connect(BASE + '/tushare.db', read_only=True)
d = c.execute("""
    select a.ts_code, a.trade_date, a.close*f.adj_factor as adjclose
    from daily a join adj_factor f using(ts_code, trade_date)
    where a.trade_date >= '20250101'
""").df().sort_values(['ts_code', 'trade_date'])
g = d.groupby('ts_code', sort=False)
d['ret'] = g['adjclose'].pct_change()
d['adj10'] = g['adjclose'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['adj10'] / d['adjclose'] - 1
d.loc[np.abs(d['fwd10']) > 5, 'fwd10'] = np.nan
d['mom10'] = g['adjclose'].transform(lambda s: s / s.shift(10) - 1)
d['vol20'] = g['ret'].transform(lambda s: s.rolling(20).std())
db = c.execute("select ts_code, trade_date, turnover_rate_f, circ_mv from daily_basic where trade_date>='20250101'").df()
d = d.merge(db, on=['ts_code', 'trade_date'])
d['lnmv'] = np.log(d['circ_mv'].clip(lower=1))
d['turn20'] = d.groupby('ts_code', sort=False)['turnover_rate_f'].transform(lambda s: s.rolling(20).mean())
bench = d.dropna(subset=['fwd10']).groupby('trade_date')['fwd10'].mean().rename('mkt')
d = d.join(bench, on='trade_date')
d['exc10'] = d['fwd10'] - d['mkt']
bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])
mf = pd.read_parquet(BASE + '/analysis/micro_feats_daily_0919.parquet')
mf['ts_code'] = mf['ts_code'].str.split('.').str[1].str.upper() + '.' + mf['ts_code'].str.split('.').str[0].str.upper()
d2 = d.merge(mf, on=['ts_code', 'trade_date'])
d2 = d2[~d2['ts_code'].isin(bad)].dropna(subset=['exc10'])
CTRL = ['lnmv', 'mom10', 'vol20', 'turn20']
d2 = d2.drop_duplicates(subset=['ts_code', 'trade_date'])
out = []
for dt, s in d2.groupby('trade_date'):
    ok = s[CTRL + ['kyle', 'amihud']].notna().all(axis=1) & s['exc10'].notna()
    ss = s[ok]
    if len(ss) < 500: continue
    X = np.column_stack([np.ones(len(ss))] + [ss[k].rank(pct=True).values for k in CTRL])
    beta_k, *_ = np.linalg.lstsq(X, ss['kyle'].rank(pct=True).values, rcond=None)
    beta_a, *_ = np.linalg.lstsq(X, ss['amihud'].rank(pct=True).values, rcond=None)
    r = ss[['exc10', 'trade_date', 'lnmv', 'turn20', 'vol20']].copy()
    r['kyle_res'] = ss['kyle'].rank(pct=True).values - X @ beta_k
    r['amihud_res'] = ss['amihud'].rank(pct=True).values - X @ beta_a
    out.append(r)
R = pd.concat(out)
for feat in ['kyle_res', 'amihud_res']:
    R['dec'] = (R.groupby('trade_date')[feat].rank(pct=True) * 10).clip(0, 9.999).astype(int)
    piv = R.groupby(['trade_date', 'dec'])['exc10'].mean().unstack()
    for yr in ['2025', '2026']:
        s = piv[piv.index.str[:4] == yr]
        means = (s.mean() * 100).round(3)
        sprd = (s[9] - s[0]).dropna()
        t = sprd.mean() / (sprd.std() / np.sqrt(len(sprd)))
        print(f'{feat} {yr}: ' + ' '.join(f'D{int(k)+1}={v:+.2f}' for k, v in means.items()) + f' | D10-D1={sprd.mean()*100:+.2f}% t={t:+.1f} n={len(sprd)}')
# D10 组合的市值/涨幅画像（确认它是什么票）
R['dec'] = (R.groupby('trade_date')['amihud_res'].rank(pct=True) * 10).clip(0, 9.999).astype(int)
for dec in [0, 9]:
    sub = R[R['dec'] == dec]
    print(f"D{dec+1} 画像: 中位流通市值={np.exp(sub['lnmv'].mean())/1e4:.1f}亿  中位turn20={sub['turn20'].median():.2f}%  中位vol20={sub['vol20'].median()*100:.2f}%")
