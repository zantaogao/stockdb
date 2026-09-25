# -*- coding: utf-8 -*-
# 裁决测试：第10天重评换仓 vs 旧票持到20天（同窗口配对，每批一个观测）
import sqlite3, duckdb, numpy as np, pandas as pd
sn = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sh = pd.read_sql("select stock_code, date, cmmr_score, fusion_score from signal_history where cmmr_score>=80", sn)
sh['date'] = sh['date'].astype(str).str.replace('-','').str[:8]
du = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = du.execute("""select d.ts_code as code, d.trade_date as dt, d.close*a.adj_factor as c
 from daily d join adj_factor a on d.ts_code=a.ts_code and d.trade_date=a.trade_date
 where d.trade_date >= '20260301'""").df().sort_values(['code','dt'])
px['code6']=px['code'].str[:6]
du.close()
piv = px.pivot_table(index='dt', columns='code6', values='c', aggfunc='last')
alldays=sorted(piv.index); didx={d:i for i,d in enumerate(alldays)}
def nw_t(x, lag=9):
    x=np.asarray([v for v in x if not pd.isna(v)]); n=len(x)
    if n<lag+3: return np.nan
    e=x-x.mean(); s=np.var(x,ddof=1)/n
    for l in range(1,lag+1): s+=2*(e[l:]*e[:-l]).mean()*(1-l/(lag+1))/n
    return x.mean()/np.sqrt(s)*np.sqrt(n) if s>0 else np.nan
def top10(dt):
    if dt not in set(sh['date']): return []
    s=sh[sh['date']==dt].sort_values(['cmmr_score','fusion_score'],ascending=False)
    return s['stock_code'].tolist()[:10]
def basket_ret(codes, d0, d1):
    r=[]
    for c in codes:
        try:
            a,b=piv.at[d0,c],piv.at[d1,c]
            if pd.isna(a) or pd.isna(b) or a<=0: continue
            r.append(b/a-1)
        except Exception: pass
    return np.mean(r) if r else np.nan
rows=[]
for dt in sorted(sh['date'].unique()):
    i0=didx.get(dt)
    if i0 is None or i0+20>=len(alldays): continue
    d10,d20=alldays[i0+10],alldays[i0+20]
    old=top10(dt)
    if len(old)<10: continue
    new=top10(d10)
    if len(new)<10: continue
    hold=basket_ret(old,d10,d20)   # 不换：旧10只 d10→d20
    swap=basket_ret(new,d10,d20)   # 换：d10新top10 d10→d20
    ov=len(set(old)&set(new))
    if pd.isna(hold) or pd.isna(swap): continue
    rows.append((dt,swap,hold,swap-hold,ov))
r=pd.DataFrame(rows,columns=['date','swap','hold','diff','overlap'])
print('批次数 %d（信号日%s起）  池内新旧平均重叠 %.1f/10 只' % (len(r), r['date'].min(), r['overlap'].mean()))
print('不换持到20天:  窗口收益均 %+.2f%%' % (r['hold'].mean()*100))
print('第10天换新10只: 窗口收益均 %+.2f%%' % (r['swap'].mean()*100))
print('配对差(换-不换): %+.2f%%  NW-t %+5.2f  换赢 %d/%d' % (r['diff'].mean()*100, nw_t(r['diff']), (r['diff']>0).sum(), len(r)))
print()
print('逐批明细:')
for _,x in r.iterrows():
    print('  %s  换 %+6.2f%%  不换 %+6.2f%%  差 %+6.2f%%  重叠%d' % (x['date'], x['swap']*100, x['hold']*100, x['diff']*100, x['overlap']))
