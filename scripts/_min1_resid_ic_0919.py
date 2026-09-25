# -*- coding: utf-8 -*-
# 1分钟微观特征终审初筛：min1_features_0902.parquet 全 16 维
# 口径 = v4f 同款：全市场截面逐日残差 RankIC vs fwd10（剥 lnmv/mom10/vol20/turn20），
# 分月 NW-t(lag10) + 全年；再算与 kyle/amihud 的截面 Spearman 相关（防重复计息）
import duckdb, numpy as np, pandas as pd, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.expanduser('~/.hermes/stockdb')
c = duckdb.connect(BASE + '/tushare.db', read_only=True)

d = c.execute("""
    select a.ts_code, a.trade_date, a.close*f.adj_factor as adjclose
    from daily a join adj_factor f using(ts_code, trade_date)
    where a.trade_date >= '20260101'
""").df().sort_values(['ts_code', 'trade_date'])
g = d.groupby('ts_code', sort=False)
d['ret'] = g['adjclose'].pct_change()
d['adj10'] = g['adjclose'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['adj10'] / d['adjclose'] - 1
d.loc[np.abs(d['fwd10']) > 5, 'fwd10'] = np.nan
d['mom10'] = g['adjclose'].transform(lambda s: s / s.shift(10) - 1)
d['vol20'] = g['ret'].transform(lambda s: s.rolling(20).std())
db = c.execute("select ts_code, trade_date, turnover_rate_f, circ_mv from daily_basic where trade_date>='20260101'").df()
d = d.merge(db, on=['ts_code', 'trade_date'])
d['lnmv'] = np.log(d['circ_mv'].clip(lower=1))
d['turn20'] = d.groupby('ts_code', sort=False)['turnover_rate_f'].transform(lambda s: s.rolling(20).mean())
bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])
d = d[~d['ts_code'].isin(bad)]

m1 = pd.read_parquet(BASE + '/analysis/min1_features_0902.parquet')
m1['code'] = m1['code'].astype(str).str.zfill(6)
m1['trade_date'] = m1['date'].astype(str)
d['code6'] = d['ts_code'].str[:6]
FEATS_ALL = ['open30_ret','tail30_ret','tail5_ret','tail_up_ratio','last_vol_share',
         'tail_vwap_dev','close_vwap_dev','vwap_dev','gap_ret','rv_1m','amp_intra',
         'vd_o30','vd_t30','vd_m1','vd_m2','day_ret']
FEATS = [f for f in FEATS_ALL if f in m1.columns]
keep = ['ts_code','code6','trade_date','fwd10','lnmv','mom10','vol20','turn20']
m1 = m1.merge(d[keep].rename(columns={'trade_date':'td2','code6':'code'}),
              left_on=['code','trade_date'], right_on=['code','td2'], how='inner')

# 与 kyle/amihud 的重叠度（逐日截面 Spearman）
mf = pd.read_parquet(BASE + '/analysis/micro_feats_daily_0919.parquet')
print('mf cols:', mf.columns.tolist())
ov = None
if all(k in mf.columns for k in ['kyle','amihud']):
    mf['trade_date'] = mf['trade_date'].astype(str).str[:8]
    mf['code'] = mf['ts_code'].str[3:9]
    ov = m1[['trade_date','code'] + FEATS].merge(mf[['trade_date','code','kyle','amihud']],
        on=['trade_date','code'], how='inner')
    print('overlap rows with kyle/amihud:', len(ov))
    cors = {}
    for dt, s in ov.groupby('trade_date'):
        if len(s) < 500: continue
        for f in ['rv_1m','tail5_ret','vwap_dev','tail30_ret']:
            ok = s[f].notna() & s['kyle'].notna()
            if ok.sum() < 500: continue
            cors.setdefault(f, []).append([
                np.corrcoef(s.loc[ok,f].rank(), s.loc[ok,'kyle'].rank())[0,1],
                np.corrcoef(s.loc[ok,f].rank(), s.loc[ok,'amihud'].rank())[0,1]])
    print(f"{'与kyle/amihud截面相关':<20} {'vs kyle':>8} {'vs amihud':>9}")
    for f, v in cors.items():
        v = np.array(v); print(f"{f:<22} {v[:,0].mean():>+8.3f} {v[:,1].mean():>+9.3f}")

FEATS = ['open30_ret','tail30_ret','tail5_ret','tail_up_ratio','last_vol_share',
         'tail_vwap_dev','close_vwap_dev','vwap_dev','gap_ret','rv_1m','amp_intra',
         'vd_o30','vd_t30','vd_m1','vd_m2','day_ret']
CTRL = ['lnmv','mom10','vol20','turn20']
FEATS = [f for f in FEATS if f in m1.columns]
rows = []
for dt, s in m1.groupby('trade_date'):
    if s['fwd10'].notna().sum() < 500: continue
    row = {'date': dt}
    ctrl_ok = s[CTRL].notna().all(axis=1) & s['fwd10'].notna()
    for f in FEATS:
        ok = ctrl_ok & s[f].notna()
        ss = s[ok]
        if len(ss) < 500: continue
        X = np.column_stack([np.ones(len(ss))] + [ss[k].rank(pct=True).values for k in CTRL])
        beta, *_ = np.linalg.lstsq(X, ss[f].rank(pct=True).values, rcond=None)
        res = ss[f].rank(pct=True).values - X @ beta
        ic = np.corrcoef(pd.Series(res).rank(), ss['fwd10'].rank())[0,1]
        raw = np.corrcoef(ss[f].rank(), ss['fwd10'].rank())[0,1]
        row[f+'_res'] = ic; row[f+'_raw'] = raw
    rows.append(row)
R = pd.DataFrame(rows).set_index('date').sort_index()
def nwt(x, l=10):
    x = np.asarray(x); x = x[~np.isnan(x)]
    if len(x) < 30: return np.nan, len(x)
    mu = x.mean(); xx = x - mu; n = len(x)
    gw = ((xx*xx).sum() + sum(2*(1-i/(l+1))*(xx[i:]*xx[:-i]).sum() for i in range(1,l+1)))/n
    return mu/np.sqrt(gw/n), n
print(f"{'因子':<16} {'区间':<9} {'残差IC':>8} {'NW-t':>6} {'n':>4} {'正率':>5}")
for f in FEATS:
    for per in sorted(set(R.index.str[:6])) + ['ALL']:
        idx = R.index if per=='ALL' else R.index.str[:6]==per
        sub = R.loc[idx][[f+'_res']].dropna()
        if len(sub) < 25: continue
        t, n = nwt(sub[f+'_res'])
        pr = (sub[f+'_res']>0).mean()*100
        print(f"{f:<16} {per:<9} {sub[f+'_res'].mean():>+8.4f} {t:>+6.1f} {n:>4} {pr:>4.0f}%")
R.to_csv(BASE + '/analysis/min1_resid_ic_0919.csv')
print('saved min1_resid_ic_0919.csv')
