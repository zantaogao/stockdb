#!/usr/bin/env python3
"""稳健版：中位数+截尾，剔除上市前30日新股，看真实规律"""
import duckdb, pandas as pd, numpy as np
from scipy import stats

con = duckdb.connect('tushare.db', read_only=True)
con.execute("ATTACH 'signals.db' AS sig (TYPE sqlite, READ_ONLY)")
pd.set_option('display.width', 220)

sig = con.execute("""
SELECT REPLACE(date,'-','') d, REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') code,
       stock_name AS "name", industry, cmmr_score cmmr, fusion_score_cmmr cmmrp
FROM sig.signal_history WHERE REPLACE(date,'-','') BETWEEN '20260801' AND '20260831'
""").df()
dates = sorted(sig['d'].unique())

dl = con.execute("""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, trade_date d, close, pct_chg
FROM daily WHERE trade_date BETWEEN '20260701' AND '20260930' AND ts_code NOT LIKE '%.BJ'
""").df()
cal = sorted(dl['d'].unique())
closes = dl.pivot(index='code', columns='d', values='close')
pcts = dl.pivot(index='code', columns='d', values='pct_chg')/100
mkt = pcts.mean(axis=0)*100
mktcum = (1+mkt/100).cumprod()
didx = {d:i for i,d in enumerate(cal)}

# 每票首个有数据日（剔新股前期暴涨）
first_day = {c: closes.loc[c].first_valid_index() for c in closes.index}
# 8月内涨停次数特征
aug_pcts = pcts.loc[:, [d for d in cal if '20260801'<=d<='20260831']]
limit_up_cnt = (aug_pcts >= 0.095).sum(axis=0)

def build(t):
    rows=[]
    for _,r in t.iterrows():
        d,c=r['d'],r['code']
        if c not in closes.index: continue
        fd = first_day[c]
        if fd is None or fd > '20260715': continue  # 剔新股
        i=didx[d]
        rec=dict(r)
        for h in (3,5,10):
            if i+h<len(cal):
                c0=closes.at[c,d]; c1=closes.at[c,cal[i+h]]
                if pd.notna(c0) and pd.notna(c1) and c0>0 and abs(c1/c0-1)<1.5:
                    rec[f'fwd{h}']=(c1/c0-1)*100
                    rec[f'exc{h}']=rec[f'fwd{h}']-(mktcum.at[cal[i+h]]/mktcum.at[d]-1)*100
                    rec['dow']=pd.Timestamp(d).day_name()[:2]
                    rec['day_mkt']=mkt[d]
                    rec['limit_ups']=int((aug_pcts[c]>=0.095).sum()) if c in aug_pcts.columns else 0
        rows.append(rec)
    return pd.DataFrame(rows)

def summarize(nm, df, col='exc5'):
    s=df[col].dropna()
    if len(s)<5: return
    t,p = stats.ttest_1samp(s,0)
    print(f"  {nm}: n={len(s)} 中位{col}={s.median():+.2f}% 均值(截尾后)={s.clip(-20,30).mean():+.2f}% 胜率={(s>0).mean()*100:.0f}% t={t:.2f} p={p:.3f}")

top_c  = sig.sort_values('cmmr', ascending=False).groupby('d').head(10).copy()
top_cp = sig.sort_values('cmmrp', ascending=False).groupby('d').head(10).copy()
tc, tp = build(top_c), build(top_cp)
tc['strat']='CMMR'; tp['strat']='CMMR+'
print(f"剔新股后样本: CMMR {len(tc)}, CMMR+ {len(tp)}")

print("\n=== A. Top10 前向收益（稳健口径：中位数/截尾均值）===")
for nm,t in [('CMMR ',tc),('CMMR+',tp)]:
    print(nm)
    for h in (3,5,10): summarize(f'fwd{h}', t, f'fwd{h}'); summarize(f'exc{h}', t, f'exc{h}')

print("\n=== B. 分数单调性（全样本抽样，exc10中位数）===")
s2 = sig.sample(min(5000,len(sig)), random_state=7).copy()
s2b = build(s2)
for scorecol in ('cmmrp','cmmr'):
    bins = [-1,20,40,60,80,300] if scorecol=='cmmrp' else [-1,20,40,60,80,100]
    s2b['b']=pd.cut(s2b[scorecol],bins)
    g=s2b.groupby('b',observed=True).agg(n=('exc10','size'),中位exc10=('exc10','median'),胜率=('exc10',lambda x:(x>0).mean()*100))
    print(scorecol); print(g.round(2).to_string())

print("\n=== C. 星期效应（两策略Top10合并，exc5）===")
both=pd.concat([tc,tp])
for dow in ['Mon','Tue','Wed','Thu','Fri']:
    summarize(dow, both[both.get('dow')==dow])

print("\n=== D. 大盘环境（信号日大盘涨/跌后的Top10 exc5）===")
both2=pd.concat([tc,tp]); both2['up']=both2['day_mkt']>0.5
for strat in ('CMMR','CMMR+'):
    for up,lab in [(True,'大盘涨日'),(False,'大盘跌/平日')]:
        summarize(f"{strat} {lab}", both2[(both2.strat==strat)&(both2.up==up)])

print("\n=== E. 连板/近期涨停数 vs 后续（Top10合并，exc5）===")
both2['lu_bucket']=pd.cut(both2['limit_ups'],[-1,0,1,3,20],labels=['0次','1次','2-3次','>3次'])
g=both2.groupby('lu_bucket',observed=True).agg(n=('exc5','size'),中位exc5=('exc5','median'),胜率=('exc5',lambda x:(x>0).mean()*100))
print(g.round(2).to_string())

print("\n=== F. CMMR+分量拆解：模型主导 vs 形态主导（稳健）===")
s3=build(sig[(sig['cmmr']>=60)|(sig['cmmrp']>=60)])
a=s3[(s3['cmmrp']>=80)&(s3['cmmr']<40)]; b=s3[(s3['cmmr']>=80)&(s3['cmmrp']<40)]
c=s3[(s3['cmmr']>=80)&(s3['cmmrp']>=80)]; mid=s3[(s3['cmmr']>=40)&(s3['cmmr']<80)&(s3['cmmrp']>=40)&(s3['cmmrp']<80)]
summarize('模型主导(cmmrp≥80,cmmr<40)',a,'exc10'); summarize('形态主导(cmmr≥80,cmmrp<40)',b,'exc10')
summarize('双高(都≥80)',c,'exc10'); summarize('双中(40-80)',mid,'exc10')

print("\n=== G. 重复上榜 vs 单次（exc5中位）===")
for nm,t in [('CMMR ',tc),('CMMR+',tp)]:
    cnt=t.groupby('code').size(); t2=t.copy(); t2['nt']=t2['code'].map(cnt)
    summarize(f"{nm}重复≥3次", t2[t2.nt>=3]); summarize(f"{nm}单次/低频", t2[t2.nt<3])

print("\n=== H. Top10分位数收益分布（exc5 p10/p25/p50/p75/p90）===")
for nm,t in [('CMMR ',tc),('CMMR+',tp)]:
    s=t['exc5'].dropna()
    print(nm, s.quantile([.1,.25,.5,.75,.9]).round(2).to_dict())