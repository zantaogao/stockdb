# -*- coding: utf-8 -*-
# 第四轮初筛：主力资金流(money_flow 2007-今日频)、估值(dividend_yield/ps/pcf)、回购事件
# 口径对齐 v4f：全市场截面逐日 RankIC vs fwd10，残差化剥 lnmv/mom10/vol20/turn20，2025/2026 分年 NW-t(lag10)
import duckdb, numpy as np, pandas as pd, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.expanduser('~/.hermes/stockdb')
c = duckdb.connect(BASE + '/tushare.db', read_only=True)

d = c.execute("""
    select a.ts_code, a.trade_date, a.close*f.adj_factor as adjclose
    from daily a join adj_factor f using(ts_code, trade_date)
    where a.trade_date >= '20240601'
""").df().sort_values(['ts_code', 'trade_date'])
g = d.groupby('ts_code', sort=False)
d['ret'] = g['adjclose'].pct_change()
d['adj10'] = g['adjclose'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['adj10'] / d['adjclose'] - 1
d.loc[np.abs(d['fwd10']) > 5, 'fwd10'] = np.nan
d['mom10'] = g['adjclose'].transform(lambda s: s / s.shift(10) - 1)
d['vol20'] = g['ret'].transform(lambda s: s.rolling(20).std())
db = c.execute("select ts_code, trade_date, turnover_rate_f, circ_mv, pe_ttm, pb, ps_ttm from daily_basic where trade_date>='20240601'").df()
d = d.merge(db, on=['ts_code', 'trade_date'])
d['lnmv'] = np.log(d['circ_mv'].clip(lower=1))
d['turn20'] = d.groupby('ts_code', sort=False)['turnover_rate_f'].transform(lambda s: s.rolling(20).mean())

# 主力资金流: stock_code 6位 + date；main_pct 已有；另算 5/10 日累计净买率
mf = c.execute("""
    select stock_code as code, strftime(date, '%Y%m%d') as trade_date,
           main_net, total_buy+total_sell as tvol, main_pct
    from money_flow where date >= '2024-06-01'
""").df()
mf['net_rate'] = np.where(mf['tvol'] > 0, mf['main_net'] / mf['tvol'] * 100, np.nan)
mf['ts_code'] = mf['code'] + np.where(mf['code'].str[0] == '6', '.SH', '.SZ')
mf = mf.sort_values(['ts_code', 'trade_date'])
mg = mf.groupby('ts_code', sort=False)
mf['mnet5'] = mg['net_rate'].transform(lambda s: s.rolling(5).mean())
mf['mnet10'] = mg['net_rate'].transform(lambda s: s.rolling(10).mean())
mf['mnet20'] = mg['net_rate'].transform(lambda s: s.rolling(20).mean())
d = d.merge(mf[['ts_code', 'trade_date', 'net_rate', 'mnet5', 'mnet10', 'mnet20']], on=['ts_code', 'trade_date'], how='left')

# 估值维（daily_basic 现成 pe_ttm/pb/ps_ttm 已并入；股息率用 valuation 表，stock_code 6位）
dv = c.execute("""
    select stock_code as code, strftime(date, '%Y%m%d') as trade_date, dividend_yield, ps, pcf
    from stock_valuation where date >= '2024-06-01'
""").df()
dv['ts_code'] = dv['code'] + np.where(dv['code'].str[0] == '6', '.SH', '.SZ')
dv = dv[['ts_code', 'trade_date', 'dividend_yield', 'ps', 'pcf']]
d = d.merge(dv, on=['ts_code', 'trade_date'], how='left')

# 回购：近60日有回购完成/实施中公告（事件哑变量，滚动窗口）
rp = c.execute("select ts_code, ann_date from repurchase where ann_date >= '20230101'").df()
rp = rp[rp['ann_date'].notna() & (rp['ann_date'] != '')]
d = d.merge(rp.rename(columns={'ann_date': 'rp_date'}).assign(rp_flag=1),
            left_on=['ts_code', d['trade_date'].values], right_on=['ts_code', 'rp_date'], how='left') if False else d
# 简化: 逐票把回购日集合化，60日窗内 any
rp_map = rp.groupby('ts_code')['ann_date'].apply(lambda s: sorted(set(s))).to_dict()
def rp60(row):
    dates = rp_map.get(row['ts_code'])
    if not dates: return 0.0
    lo = (pd.Timestamp(row['trade_date']) - pd.Timedelta(days=90)).strftime('%Y%m%d')
    hi = row['trade_date']
    return 1.0 if any(lo <= x <= hi for x in dates) else 0.0
d['rp60'] = d.apply(rp60, axis=1)

bench = d.dropna(subset=['fwd10']).groupby('trade_date')['fwd10'].mean().rename('mkt')
d = d.join(bench, on='trade_date')
d['exc10'] = d['fwd10'] - d['mkt']
bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])
d = d[~d['ts_code'].isin(bad)]

FEATS = ['net_rate', 'mnet5', 'mnet10', 'mnet20', 'dividend_yield', 'ps', 'pcf', 'pe_ttm', 'pb', 'ps_ttm', 'rp60']
CTRL = ['lnmv', 'mom10', 'vol20', 'turn20']
d = d.drop_duplicates(['ts_code', 'trade_date'])
rows = []
for dt, s in d.groupby('trade_date'):
    if s['exc10'].notna().sum() < 500: continue
    row = {'date': dt}
    ctrl_ok = s[CTRL].notna().all(axis=1) & s['exc10'].notna()
    Xall = np.column_stack([np.ones(ctrl_ok.sum())] + [s.loc[ctrl_ok, k].rank(pct=True).values for k in CTRL])
    for f in FEATS:
        ok = ctrl_ok & s[f].notna()
        ss = s[ok]
        if len(ss) < 500: continue
        X = np.column_stack([np.ones(len(ss))] + [ss[k].rank(pct=True).values for k in CTRL])
        beta, *_ = np.linalg.lstsq(X, ss[f].rank(pct=True).values, rcond=None)
        res = ss[f].rank(pct=True).values - X @ beta
        ic = np.corrcoef(pd.Series(res).rank(), ss['exc10'].rank())[0, 1]
        raw = np.corrcoef(ss[f].rank(), ss['exc10'].rank())[0, 1]
        row[f + '_res'] = ic; row[f + '_raw'] = raw
    rows.append(row)
R = pd.DataFrame(rows).set_index('date')
def nwt(x, l=10):
    x = np.asarray(x); x = x[~np.isnan(x)]
    if len(x) < 30: return np.nan, len(x)
    mu = x.mean(); xx = x - mu; n = len(x)
    gw = ((xx*xx).sum() + sum(2*(1-i/(l+1))*(xx[i:]*xx[:-i]).sum() for i in range(1, l+1)))/n
    return mu/np.sqrt(gw/n), n
print(f"{'因子':<16} {'年':<6} {'残差IC':>8} {'NW-t':>6} {'n':>4} {'正率':>5}   {'原始IC':>8}")
for f in FEATS:
    for yr in ['2025', '2026']:
        sub = R[R.index.str[:4] == yr][[f+'_res', f+'_raw']].dropna()
        if len(sub) < 30: continue
        t, n = nwt(sub[f+'_res'])
        pr = (sub[f+'_res'] > 0).mean()*100
        print(f"{f:<16} {yr:<6} {sub[f+'_res'].mean():>+8.4f} {t:>+6.1f} {n:>4} {pr:>4.0f}%   {sub[f+'_raw'].mean():>+8.4f}")
