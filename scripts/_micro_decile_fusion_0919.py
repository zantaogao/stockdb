# a) 十分位分组收益（多头/空头拆解） b) 与生产fusion重叠度 + fusion池内Amihud增强top10
import duckdb, numpy as np, pandas as pd, sqlite3, os

BASE = os.path.expanduser('~/.hermes/stockdb')
c = duckdb.connect(BASE + '/tushare.db', read_only=True)

d = c.execute("""
    select a.ts_code, a.trade_date, a.close*f.adj_factor as adjclose
    from daily a join adj_factor f using(ts_code, trade_date)
    where a.trade_date >= '20250101'
""").df().sort_values(['ts_code', 'trade_date'])
g = d.groupby('ts_code', sort=False)
d['adj10'] = g['adjclose'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['adj10'] / d['adjclose'] - 1
d.loc[np.abs(d['fwd10']) > 5, 'fwd10'] = np.nan
bench = d.dropna(subset=['fwd10']).groupby('trade_date')['fwd10'].mean().rename('mkt')
d = d.join(bench, on='trade_date')
d['exc10'] = d['fwd10'] - d['mkt']

bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])

mf = pd.read_parquet(BASE + '/analysis/micro_feats_daily_0919.parquet')
mf['ts_code'] = mf['ts_code'].str.split('.').str[1].str.upper() + '.' + mf['ts_code'].str.split('.').str[0].str.upper()
d2 = d.merge(mf, on=['ts_code', 'trade_date'])
d2 = d2[~d2['ts_code'].isin(bad)].dropna(subset=['exc10'])

# ── a) 十分位分组（rank by feature daily, D10=最高流动性成本组）
for feat in ['kyle', 'amihud']:
    d2[f'{feat}_d'] = d2.groupby('trade_date')[feat].transform(lambda s: pd.qcut(s.rank(method='first'), 10, labels=False))
print('===== a) 十分位 10d超额均值(%)  D1=流动性成本最低 ... D10=最高 =====')
for feat in ['kyle', 'amihud']:
    piv = d2.dropna(subset=[f'{feat}_d']).groupby(['trade_date', f'{feat}_d'])['exc10'].mean().unstack()
    for yr in ['2025', '2026']:
        s = piv[piv.index.str[:4] == yr]
        means = (s.mean() * 100).round(3)
        # D10-D1 价差 t 检验
        sprd = (s[9] - s[0]).dropna()
        t = sprd.mean() / (sprd.std() / np.sqrt(len(sprd)))
        print(f'{feat} {yr}: ' + ' '.join(f'D{int(k)+1}={v:+.2f}' for k, v in means.items()) + f'  | D10-D1={sprd.mean()*100:+.2f}% t={t:+.1f} n={len(sprd)}')

# ── b) 与生产 fusion_score 重叠
sig = sqlite3.connect(BASE + '/signals.db')
sh = pd.read_sql("select stock_code, date, fusion_score, reg10_pred from signal_history where fusion_score is not null", sig)
# 归一化: date->YYYYMMDD, stock_code 可能裸码
sh['trade_date'] = sh['date'].str.replace('-', '')
sh['ts_code'] = sh['stock_code'].str.extract(r'^(\d{6})')[0].map(
    lambda x: x + ('.SH' if x.startswith(('6', '9')) else ('.SZ' if x.startswith(('0', '2', '3')) else '.BJ')))
sh = sh.dropna(subset=['ts_code']).drop_duplicates(['ts_code', 'trade_date'])
m = d2.merge(sh[['ts_code', 'trade_date', 'fusion_score']], on=['ts_code', 'trade_date'])
print(f'\n===== b) fusion覆盖日样本 {len(m)} 天 =====')

# 截面重叠：每日 fusion top10% 与 amihud top10% 的交集比例、特征间rank IC
m = m.dropna(subset=['amihud', 'kyle'])
m['am_d'] = (m.groupby('trade_date')['amihud'].rank(pct=True) * 10).clip(0, 9.999).astype(int)
m['fu_d'] = (m.groupby('trade_date')['fusion_score'].rank(pct=True) * 10).clip(0, 9.999)
m = m.dropna(subset=['fu_d'])
m['fu_d'] = m['fu_d'].astype(int)
ov = m.groupby('trade_date').apply(lambda s: len(set(s[s['am_d'] == 9].index) & set(s[s['fu_d'] == 9].index)) / max((s['fu_d'] == 9).sum(), 1), include_groups=False)
print(f'amihud top10% 与 fusion top10% 日均重叠率: {ov.mean()*100:.1f}% (随机=10%)')
ric = m.groupby('trade_date').apply(lambda s: s['amihud'].corr(s['fusion_score'], method='spearman') if len(s) > 500 else np.nan, include_groups=False).dropna()
for yr in ['2025', '2026']:
    s = ric[ric.index.str[:4] == yr]
    if len(s) > 10:
        print(f'rankIC(amihud, fusion_score) {yr}: {s.mean():+.4f} (n={len(s)})')

# fusion 池内增强：fusion top15% 池 → 按 amihud 排 top10 vs fusion 原序 top10
rows = []
for dt, s in m.dropna(subset=['fusion_score', 'exc10']).groupby('trade_date'):
    if len(s) < 500: continue
    thr = s['fusion_score'].quantile(0.85)
    pool = s[s['fusion_score'] >= thr]
    if len(pool) < 20: continue
    fu_top = pool.nlargest(10, 'fusion_score')['exc10'].mean()
    am_top = pool.nlargest(10, 'amihud')['exc10'].mean()
    fu_all = pool['exc10'].mean()
    rows.append((dt, fu_top, am_top, fu_all))
r = pd.DataFrame(rows, columns=['dt', 'fu_top', 'am_top', 'fu_pool']).dropna()
for yr in ['2025', '2026']:
    s = r[r['dt'].str[:4] == yr]
    if len(s) < 10: continue
    for lbl, col in [('fusion原序top10', 'fu_top'), ('池内amihud top10', 'am_top'), ('池全体等权', 'fu_pool')]:
        print(f'{yr} {lbl}: 10d超额均值={s[col].mean()*100:+.2f}%')
    dif = (s['am_top'] - s['fu_top']).dropna()
    t = dif.mean() / (dif.std() / np.sqrt(len(dif)))
    print(f'{yr} 配对差(am_top - fu_top): {dif.mean()*100:+.2f}pp  t={t:+.1f}  am更优天数={(dif>0).mean()*100:.0f}%  n={len(dif)}')
