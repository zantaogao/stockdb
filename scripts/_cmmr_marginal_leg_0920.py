# -*- coding: utf-8 -*-
# cmmr 80+ top10 的边际持有腿检验：前10天段 vs 第10→20天段（配对+NW lag9）
import sqlite3, duckdb, numpy as np, pandas as pd
sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select stock_code, date, cmmr_score, fusion_score from signal_history where cmmr_score>=80", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""
  select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
  from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
  where d.trade_date >= '20260301'""").df().sort_values(['code','dt'])
px['code6']=px['code'].str[:6]
du.close()
piv = px.pivot_table(index='dt', columns='code6', values='c', aggfunc='last')
alldays = sorted(piv.index)
didx = {d:i for i,d in enumerate(alldays)}
def nw_t(x, lag=9):
    x=np.asarray([v for v in x if not pd.isna(v)]); n=len(x)
    if n<lag+3: return np.nan
    e=x-x.mean(); s=np.var(x,ddof=1)/n
    for l in range(1,lag+1): s+=2*(e[l:]*e[:-l]).mean()*(1-l/(lag+1))/n
    return x.mean()/np.sqrt(s)*np.sqrt(n) if s>0 else np.nan
rows=[]
for dt, sub in sh.groupby('date'):
    i0 = didx.get(dt)
    if i0 is None: continue
    i10, i20 = i0+10, i0+20
    if i20 >= len(alldays): continue
    d10, d20 = alldays[i10], alldays[i20]
    sub = sub.sort_values(['cmmr_score','fusion_score'], ascending=False).head(10)
    m1=[];m2=[]
    for c in sub['stock_code']:
        try:
            c0=piv.at[dt,c]; ca=piv.at[d10,c]; cb=piv.at[d20,c]
            if any(pd.isna(v) for v in (c0,ca,cb)) or c0<=0: continue
            m1.append(ca/c0-1); m2.append(cb/ca-1)
        except Exception: pass
    if m1: rows.append((dt, np.mean(m1), np.mean(m2), len(m1)))
r=pd.DataFrame(rows, columns=['date','leg1_10','leg11_20','n'])
print('成熟批次 %d 个（每批=当日fusion键top10等权）' % len(r))
print('前10天段:   均 %+.2f%%/批  NW-t %+5.2f  正批 %d/%d' % (r['leg1_10'].mean()*100, nw_t(r['leg1_10']), (r['leg1_10']>0).sum(), len(r)))
print('第10→20段:  均 %+.2f%%/批  NW-t %+5.2f  正批 %d/%d' % (r['leg11_20'].mean()*100, nw_t(r['leg11_20']), (r['leg11_20']>0).sum(), len(r)))
d = r['leg11_20']-r['leg1_10']
print('边际腿-前段 配对差 %+.2f%% NW-t %+5.2f 正批 %d/%d' % (d.mean()*100, nw_t(d), (d>0).sum(), len(r)))
# 全池口径对照（不选top10，80+全池等权）
rows2=[]
for dt, sub in sh.groupby('date'):
    i0=didx.get(dt)
    if i0 is None: continue
    if i0+20>=len(alldays): continue
    d10,d20=alldays[i0+10],alldays[i0+20]
    m1=[];m2=[]
    for c in sub['stock_code']:
        try:
            c0=piv.at[dt,c];ca=piv.at[d10,c];cb=piv.at[d20,c]
            if any(pd.isna(v) for v in (c0,ca,cb)) or c0<=0: continue
            m1.append(ca/c0-1);m2.append(cb/ca-1)
        except Exception: pass
    if m1: rows2.append((dt,np.mean(m1),np.mean(m2)))
r2=pd.DataFrame(rows2, columns=['date','leg1_10','leg11_20'])
print('\n80+全池口径（%d批）: 前10天 %+.2f%% | 10→20段 %+.2f%% (正批%d/%d)' % (
    len(r2), r2['leg1_10'].mean()*100, r2['leg11_20'].mean()*100, (r2['leg11_20']>0).sum(), len(r2)))
