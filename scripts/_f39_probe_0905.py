# -*- coding: utf-8 -*-
"""f39/f41 深挖：f39 只在触发票内部算IC+分组；f41 查为何消失；f43/f39 相关性"""
import duckdb, numpy as np, pandas as pd
BASE='/Users/zantao/.hermes/stockdb'
f=pd.read_parquet(BASE+'/analysis/retrain_10d_v4/_uncon_feats.parquet')
con=duckdb.connect(BASE+'/tushare.db',read_only=True)
af=con.execute("select ts_code,trade_date,adj_factor,close from (select a.ts_code,a.trade_date,a.adj_factor,d.close from adj_factor a join daily d on a.ts_code=d.ts_code and a.trade_date=d.trade_date) where trade_date>='20241201'").df()
con.close()
def fmt(s):
    s=s.astype(str); return np.where(s.str.contains('-'),s,s.str[:4]+'-'+s.str[4:6]+'-'+s.str[6:8])
af['date']=fmt(af.trade_date); af['symbol']=af.ts_code.str[:6]
af=af.sort_values(['symbol','date'])
af['adjclose']=af.close*af.adj_factor
af['fwd10']=af.groupby('symbol').adjclose.transform(lambda s:s.shift(-10)/s-1)
m=f.merge(af[['symbol','date','fwd10']],on=['symbol','date'],how='inner')
ev=m[m.date>='2025-01-01'].replace([np.inf,-np.inf],np.nan)

print('f41 缺失率:',ev.f41_retail_crowd20.isna().mean() if 'f41_retail_crowd20' in ev else '列不存在')

# f39 触发子集内部
sub=ev[ev.f39_vol_diverge.notna() & ev.fwd10.notna()]
rows=[]
for kind,ddf in [('触发子集',sub),('全市场',ev[ev.f39_vol_diverge.notna()|ev.f31_touch20.notna()])]:
    ics={}
    for dt,dg in ddf.groupby('date'):
        if len(dg)<50: continue
        ics[dt]=dg['f39_vol_diverge'].rank().corr(dg['fwd10'].rank())
    s=pd.Series(ics).dropna()
    for yr in ['2025','2026']:
        ss=s[s.index.astype(str).str[:4]==yr]
        if len(ss)>20:
            rows.append((kind,yr,len(ss),round(ss.mean(),4),round(ss.mean()/ss.std()*np.sqrt(len(ss)),2),round((ss>0).mean(),3)))
for r in rows: print(*r)

# 触发子集内十分组收益（按f39排序）
sub2=sub.dropna(subset=['f39_vol_diverge','fwd10'])
pairs=sorted(zip(sub2.f39_vol_diverge,sub2.fwd10))
n=len(pairs); d10=n//10
print('触发子集十分组(按f39升序):',' '.join(f'D{k+1}:{np.mean([r for _,r in pairs[k*d10:(k+1)*d10]])*100:+.2f}%' for k in range(10)))

# f39 与已验证特征的相关性（秩）
cols=['f39_vol_diverge','f31_touch20','f32_wick20','f33_pvcorr20','f43_turn_cv20','f42_ln_circmv','f45_skew60']
c=sub2[cols].dropna().corr(method='spearman')
print(c.round(3).to_string())