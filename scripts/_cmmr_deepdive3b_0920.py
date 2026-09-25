# -*- coding: utf-8 -*-
# cmmr 深究 v3b：档内组合配对（os深跌 vs 其他）+ 排除100分池配对；NW lag20（20d窗口全重叠）
import sqlite3, duckdb, numpy as np, pandas as pd
sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select stock_code, date, cmmr_score, fusion_score from signal_history where cmmr_score>=80 and date>='20260701'", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""
  select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c, d.vol as v
  from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
  where d.trade_date >= '20260301'""").df().sort_values(['code','dt'])
g = px.groupby('code')
px['ma40'] = g['c'].transform(lambda s: s.rolling(40).mean())
px['slope'] = (px['ma40']-g['ma40'].transform(lambda s: s.shift(20)))/g['ma40'].transform(lambda s: s.shift(20))
px['chg10'] = g['c'].transform(lambda s: s/s.shift(10)-1)
px['fwd20'] = g['c'].transform(lambda s: s.shift(-20)/s-1)
px['fwd10'] = g['c'].transform(lambda s: s.shift(-10)/s-1)
px['code6'] = px['code'].str[:6]
du.close()
mkt20 = px.groupby('dt')['fwd20'].mean(); mkt10 = px.groupby('dt')['fwd10'].mean()
m = sh.merge(px[['code6','dt','fwd20','fwd10','slope','chg10']], left_on=['stock_code','date'], right_on=['code6','dt'])
m['ex20'] = m['fwd20'] - m['date'].map(mkt20)
m['ex10'] = m['fwd10'] - m['date'].map(mkt10)
m['os40'] = m['chg10'] < -0.08
def nw_t(x, lag=20):
    x=np.asarray(x.dropna()) if hasattr(x,'dropna') else np.asarray(x); n=len(x)
    if n<lag+3: return np.nan
    e=x-x.mean(); s=np.var(x,ddof=1)/n
    for l in range(1,lag+1): s+=2*(e[l:]*e[:-l]).mean()*(1-l/(lag+1))/n
    return x.mean()/np.sqrt(s)*np.sqrt(n) if s>0 else np.nan
rows=[]
for dt, sub in m.groupby('date'):
    s20 = sub.dropna(subset=['fwd20'])
    if len(s20)<20: continue
    a = s20[s20['os40']]; b = s20[~s20['os40']]
    c1 = s20[s20['cmmr_score']==100]; c2 = s20[s20['cmmr_score']==80]
    rows.append((dt, len(s20),
        a['ex20'].mean() if len(a)>=5 else np.nan,
        b['ex20'].mean() if len(b)>=5 else np.nan,
        (a.dropna(subset=['fusion_score']).nlargest(min(10,len(a)),'fusion_score')['ex20'].mean()) if len(a)>=10 else np.nan,
        (b.dropna(subset=['fusion_score']).nlargest(min(10,len(b)),'fusion_score')['ex20'].mean()) if len(b)>=10 else np.nan,
        c1['ex20'].mean() if len(c1)>=5 else np.nan,
        c2['ex20'].mean() if len(c2)>=5 else np.nan))
r = pd.DataFrame(rows, columns=['date','n','os40池','浅调池','os40top10','浅调top10','分100','分80'])
print('交易日 %d' % len(r))
for name in ('os40池','浅调池','os40top10','浅调top10','分100','分80'):
    print('  %-9s 日均 %+5.2f%%  有数天 %d' % (name, r[name].mean()*100, r[name].notna().sum()))
d = r['os40池']-r['浅调池']; print('配对① os深跌池-浅调池: %+5.2f%% NW-t %+5.2f 正天 %d/%d' % (d.mean()*100, nw_t(d), (d>0).sum(), d.notna().sum()))
d = r['os40top10']-r['浅调top10']; print('配对② 各自fusion top10:  %+5.2f%% NW-t %+5.2f 正天 %d/%d' % (d.mean()*100, nw_t(d), (d>0).sum(), d.notna().sum()))
d = r['分100']-r['分80']; print('配对③ 100分池-80分池:   %+5.2f%% NW-t %+5.2f 正天 %d/%d' % (d.mean()*100, nw_t(d), (d>0).sum(), d.notna().sum()))
