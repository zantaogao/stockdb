# 微观结构信号初筛：Kyle lambda / Amihud / 上行量占比（5分钟库）
# 截面日频 RankIC vs fwd10，残差化(剥市值/动量/波动/换手)，2025/2026分年 t 检验
import duckdb, numpy as np, pandas as pd, glob, os

BASE = os.path.expanduser('~/.hermes/stockdb')
c = duckdb.connect(BASE + '/tushare.db', read_only=True)

# 日线 → adjclose, fwd10, 控制变量
d = c.execute("""
    select a.ts_code, a.trade_date, a.close,
           a.close*f.adj_factor as adjclose
    from daily a join adj_factor f using(ts_code, trade_date)
    where a.trade_date >= '20250101'
""").df()
d = d.sort_values(['ts_code', 'trade_date'])
g = d.groupby('ts_code', sort=False)
d['ret'] = g['adjclose'].pct_change()
d['adj10'] = g['adjclose'].transform(lambda s: s.shift(-10))
d['fwd10'] = d['adj10'] / d['adjclose'] - 1
d['mom10'] = g['adjclose'].transform(lambda s: s / s.shift(10) - 1)
d['vol20'] = g['ret'].transform(lambda s: s.rolling(20).std())
for col in ['ret', 'fwd10', 'mom10', 'vol20']:
    d.loc[np.abs(d[col]) > 5, col] = np.nan
# 换手、市值
db = c.execute("""
    select ts_code, trade_date, turnover_rate_f, circ_mv from daily_basic where trade_date>='20250101'
""").df()
d = d.merge(db, on=['ts_code', 'trade_date'])
d['lnmv'] = np.log(d['circ_mv'].clip(lower=1))
d['turn20'] = d.groupby('ts_code', sort=False)['turnover_rate_f'].transform(lambda s: s.rolling(20).mean())

bad = set(c.execute("select ts_code from stock_basic where name like '%ST%' or ts_code like '%.BJ'").df()['ts_code'])

# 5分钟特征（逐票）
CACHE = BASE + '/analysis/micro_feats_daily_0919.parquet'
if os.path.exists(CACHE):
    mf = pd.read_parquet(CACHE)
    # 归一化代码: 'sh.600000' -> '600000.SH'
    mf['ts_code'] = mf['ts_code'].str.split('.').str[1].str.upper() + '.' + mf['ts_code'].str.split('.').str[0].str.upper()
    print('loaded cache micro rows:', len(mf), flush=True)
else:
 feats = []
 files = sorted(glob.glob(BASE + '/minutes/5min/*.parquet'))
 print('files:', len(files), flush=True)
 for i, fp in enumerate(files):
    try:
        m = pd.read_parquet(fp, columns=['date', 'close', 'volume', 'amount'])
    except Exception:
        continue
    m = m[m['volume'] > 0].copy()
    m['barret'] = m['close'].pct_change()
    m['sign'] = (m.groupby('date')['close'].diff() > 0).astype(float)
    a = m.groupby('date').apply(
        lambda x: pd.Series({
            'kyle': np.mean(np.abs(x['barret']) / (x['volume'] + 1) * 1e8),
            'amihud': np.mean(np.abs(x['barret']) / (x['amount'] + 1) * 1e10),
            'upvol': x['volume'][x['sign'] > 0].sum() / max(x['volume'].sum(), 1),
        }), include_groups=False)
    a = a.reset_index()
    ts = 'sh.' + fp.split('_')[1].split('.')[0] if 'sh_' in fp else 'sz.' + fp.split('_')[1].split('.')[0]
    a['ts_code'] = ts
    a['trade_date'] = a['date'].astype(str).str.replace('-', '')
    feats.append(a[['ts_code', 'trade_date', 'kyle', 'amihud', 'upvol']])
    if i % 1000 == 0: print(i, flush=True)
 mf = pd.concat(feats, ignore_index=True)
 print('micro rows:', len(mf), flush=True)
 mf.to_parquet(CACHE)

d2 = d.merge(mf, on=['ts_code', 'trade_date'])
d2 = d2[~d2['ts_code'].isin(bad)].dropna(subset=['fwd10'])
CTRL = ['lnmv', 'mom10', 'vol20', 'turn20']

def resid_ic(df, feat):
    out = []
    for dt, s in df.groupby('trade_date'):
        s = s.dropna(subset=[feat] + CTRL + ['fwd10'])
        if len(s) < 500: continue
        # 特征与控制变量都转 rank，OLS 取残差
        fr = s[feat].rank(pct=True).values
        X = np.column_stack([np.ones(len(s))] + [s[k].rank(pct=True).values for k in CTRL])
        beta, *_ = np.linalg.lstsq(X, fr, rcond=None)
        res = fr - X @ beta
        ic = np.corrcoef(pd.Series(res).rank(), pd.Series(s['fwd10'].values).rank())[0, 1]
        out.append((dt, ic))
    return pd.Series(dict(out)).dropna()

for feat in ['kyle', 'amihud', 'upvol']:
    raw = d2.groupby('trade_date').apply(
        lambda s: s[feat].corr(s['fwd10'], method='spearman') if s[feat].notna().sum() > 500 else np.nan,
        include_groups=False).dropna()
    ric = resid_ic(d2, feat)
    ric.index = ric.index.astype(str)
    raw.index = raw.index.astype(str)
    for yr in ['2025', '2026']:
        for name, ser in [('raw', raw), ('resid', ric)]:
            s = ser[ser.index.str[:4] == yr]
            if len(s) < 20: continue
            t = s.mean() / (s.std() / np.sqrt(len(s)))
            print(f"{feat:7s} {name:5s} {yr}: n={len(s):3d} IC={s.mean():+.4f} t={t:+.1f} 正率={(s>0).mean()*100:.0f}%")
