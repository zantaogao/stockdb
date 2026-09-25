# -*- coding: utf-8 -*-
# 1分钟尾盘/隔夜特征截面初筛（2026-09-20）
# 口径同 v4f：逐日全市场残差 RankIC vs fwd10（剥 lnmv/mom10/vol20/turn20），逐月 NW-t(lag10)
# 附加：与 kyle/amihud 截面 Spearman（防与 v4f 重复计息）
import duckdb, numpy as np, pandas as pd, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.expanduser('~/.hermes/stockdb')
c = duckdb.connect(BASE + '/tushare.db', read_only=True)

d = c.execute("""
    select a.ts_code, a.trade_date, a.close*f.adj_factor as adjclose
    from daily a join adj_factor f using(ts_code, trade_date)
    where a.trade_date >= '20251001'
""").df().sort_values(['ts_code', 'trade_date'])
g = d.groupby('ts_code', sort=False)
d['ret'] = g['adjclose'].pct_change()
d['adj10'] = g['adjclose'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['adj10'] / d['adjclose'] - 1
d.loc[np.abs(d['fwd10']) > 5, 'fwd10'] = np.nan
d['mom10'] = g['adjclose'].transform(lambda s: s / s.shift(10) - 1)
d['vol20'] = g['ret'].transform(lambda s: s.rolling(20).std())
db = c.execute("select ts_code, trade_date, turnover_rate_f, circ_mv from daily_basic where trade_date>='20251001'").df()
d = d.merge(db, on=['ts_code', 'trade_date'])
d['lnmv'] = np.log(d['circ_mv'].clip(lower=1))
d['turn20'] = d.groupby('ts_code', sort=False)['turnover_rate_f'].transform(lambda s: s.rolling(20).mean())
bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])
d = d[~d['ts_code'].isin(bad)]
d['code'] = d['ts_code'].str[:6]
d = d[['code','trade_date','fwd10','lnmv','mom10','vol20','turn20']].drop_duplicates(['code','trade_date'])

m1 = pd.read_parquet(BASE + '/analysis/min1_feats_0920.parquet')
m1['trade_date'] = m1['date'].str.replace('-','')
d = d.merge(m1.drop(columns=['date']), on=['code','trade_date'], how='inner')
print('merged', len(d), 'days', d['trade_date'].nunique(), flush=True)

FEATS = ['gap_ret','tail30_ret','tail5_ret','last_vol_share','vwap_dev','tail_vwap_dev',
         'tail_up_ratio','vd_o30','vd_t30','vd_m2','ovr20']
CTRL = ['lnmv','mom10','vol20','turn20']
rows = []
for dt, s in d.groupby('trade_date'):
    if len(s) < 500: continue
    row = {'date': dt}
    ctrl_ok = s[CTRL].notna().all(axis=1) & s['fwd10'].notna()
    for f in FEATS:
        ok = ctrl_ok & s[f].notna() & np.isfinite(s[f])
        ss = s[ok]
        if len(ss) < 500: continue
        X = np.column_stack([np.ones(len(ss))] + [ss[k].rank(pct=True).values for k in CTRL])
        beta, *_ = np.linalg.lstsq(X, ss[f].rank(pct=True).values, rcond=None)
        res = ss[f].rank(pct=True).values - X @ beta
        row[f+'_res'] = np.corrcoef(pd.Series(res).rank(), ss['fwd10'].rank())[0,1]
        row[f+'_raw'] = np.corrcoef(ss[f].rank(), ss['fwd10'].rank())[0,1]
    rows.append(row)
R = pd.DataFrame(rows).set_index('date').sort_index()
def nwt(x, l=10):
    x = np.asarray(x); x = x[~np.isnan(x)]
    if len(x) < 25: return np.nan, len(x)
    mu = x.mean(); xx = x - mu; n = len(x)
    gw = ((xx*xx).sum() + sum(2*(1-i/(l+1))*(xx[i:]*xx[:-i]).sum() for i in range(1,l+1)))/n
    return mu/np.sqrt(gw/n), n
print(f"{'因子':<16} {'区间':<8} {'残差IC':>8} {'NW-t':>6} {'n':>4} {'正率':>5}")
for f in FEATS:
    for per in sorted(set(R.index.str[:6])) + ['ALL']:
        idx = list(R.index) if per=='ALL' else list(R.index[R.index.str[:6]==per])
        sub = R.loc[idx, [f+'_res']].dropna()
        if len(sub) < 20: continue
        t, n = nwt(sub[f+'_res'])
        pr = (sub[f+'_res'] > 0).mean()*100
        print(f"{f:<16} {per:<8} {sub[f+'_res'].mean():>+8.4f} {t:>+6.1f} {n:>4} {pr:>4.0f}%")
R.to_csv(BASE + '/analysis/min1_resid_ic_0920.csv')

# 与 kyle/amihud 重叠相关
mf = pd.read_parquet(BASE + '/analysis/micro_feats_daily_0919.parquet')
mf['trade_date'] = mf['trade_date'].astype(str).str[:8]
mf['code'] = mf['ts_code'].str[3:9]
ov = d[['trade_date','code'] + FEATS].merge(mf[['trade_date','code','kyle','amihud']], on=['trade_date','code'], how='inner')
print('overlap rows:', len(ov))
cors = {}
for dt, s in ov.groupby('trade_date'):
    if len(s) < 500: continue
    for f in FEATS:
        for k in ['kyle','amihud']:
            ok = s[f].notna() & np.isfinite(s[f]) & s[k].notna()
            if ok.sum() < 500: continue
            cors.setdefault((f,k), []).append(np.corrcoef(s.loc[ok,f].rank(), s.loc[ok,k].rank())[0,1])
print(f"{'因子':<16} {'vs kyle':>8} {'vs amihud':>9}")
for f in FEATS:
    a = np.mean(cors.get((f,'kyle'), [np.nan])); b = np.mean(cors.get((f,'amihud'), [np.nan]))
    print(f"{f:<16} {a:>+8.3f} {b:>+9.3f}")
print('saved min1_resid_ic_0920.csv', flush=True)
