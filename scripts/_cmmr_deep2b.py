#!/usr/bin/env python3
"""E4-E7 重跑（mom10先attach再排序）"""
import duckdb, pandas as pd, numpy as np
from scipy import stats

con = duckdb.connect('tushare.db', read_only=True)
con.execute("ATTACH 'signals.db' AS sig (TYPE sqlite, READ_ONLY)")
pd.set_option('display.width', 240)

sig = con.execute("""
SELECT REPLACE(date,'-','') d, REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') code,
 stock_name AS "name", cmmr_score cmmr, fusion_score_cmmr cmmrp, old_score, ma40_slope
FROM sig.signal_history WHERE REPLACE(date,'-','')>='20260801'
""").df()
dl = con.execute("""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, trade_date d, open, close, pct_chg/100 p
FROM daily WHERE trade_date>='20260601' AND ts_code NOT LIKE '%.BJ'""").df()
cal=sorted(dl['d'].unique()); closes=dl.pivot(index='code',columns='d',values='close')
opens=dl.pivot(index='code',columns='d',values='open'); pcts=dl.pivot(index='code',columns='d',values='p')
mkt=pcts.mean(axis=0)*100; mktcum=(1+mkt/100).cumprod(); didx={d:i for i,d in enumerate(cal)}
first={c:closes.loc[c].first_valid_index() for c in closes.index}
mom10 = closes.pct_change(10, axis=1, fill_method=None)*100

def add_fwd(df, hs=(5,10)):
    out=[]
    for _,r in df.iterrows():
        c,d=r['code'],r['d']
        if c not in closes.index: continue
        if first[c] is None or str(first[c])>'20260715': continue
        i=didx[d]; rec=dict(r)
        c0=closes.at[c,d] if d in closes.columns else np.nan
        for h in hs:
            if i+h<len(cal):
                c1=closes.at[c,cal[i+h]]
                if pd.notna(c0) and pd.notna(c1) and c0>0 and abs(c1/c0-1)<1.5:
                    rec[f'fwd{h}']=(c1/c0-1)*100
                    rec[f'exc{h}']=rec[f'fwd{h}']-(mktcum.at[cal[i+h]]/mktcum.at[d]-1)*100
        if i+1<len(cal):
            o=opens.at[c,cal[i+1]]
            if pd.notna(c0) and pd.notna(o): rec['open_premium']=(o/c0-1)*100
        if d in mom10.columns and c in mom10.index:
            m=mom10.at[c,d]
            if pd.notna(m): rec['mom10']=m
        out.append(rec)
    return pd.DataFrame(out)

def stat(s,label):
    s=pd.Series(s).dropna()
    if len(s)<10: print(f"  {label}: n={len(s)} 样本不足"); return
    t,p=stats.ttest_1samp(s.clip(-20,30),0)
    print(f"  {label}: n={len(s)} 中位={s.median():+.2f}% 胜率={(s>0).mean()*100:.0f}% p={p:.3f}")

print("=== E4. 并列破解：cmmr≥80池内按mom10排序选6只，跌最深 vs 跌最浅 ===")
for asc_, lab in [(True,'跌最深(深超卖)'),(False,'跌最浅(浅回调)')]:
    tmp = sig[sig.cmmr>=80].copy()
    tmp['mom10'] = [mom10.at[c,d] if c in mom10.index and d in mom10.columns else np.nan for c,d in zip(tmp.code,tmp.d)]
    pick = tmp.sort_values(['d','mom10'],ascending=[True,asc_]).groupby('d').head(6)
    pb = add_fwd(pick, hs=(5,))
    stat(pb['exc5'], lab)

t10  = add_fwd(sig.sort_values('cmmr',ascending=False).groupby('d').head(10))
t10p = add_fwd(sig.sort_values('cmmrp',ascending=False).groupby('d').head(10))
print("\n=== E4b. 次日开盘溢价（能不能上车）===")
print(f"  CMMR Top10: 开盘溢价中位{t10['open_premium'].median():+.2f}% 高开>2%占{(t10.open_premium>2).mean()*100:.0f}%")
print(f"  CMMR+Top10: 开盘溢价中位{t10p['open_premium'].median():+.2f}% 高开>2%占{(t10p.open_premium>2).mean()*100:.0f}%")
# 信号收益里多少来自当天收盘前的信息？次日开盘→5日的收益 vs 收盘→5日
print("\n=== E4c. 收益来源拆解：exc5里开盘溢价 vs 开盘后续 ===")
for nm,q in [('CMMR',t10),('CMMR+',t10p)]:
    s=q.dropna(subset=['open_premium','exc5'])
    print(f"  {nm}: exc5中位{s.exc5.median():+.2f}% 其中开盘溢价{s.open_premium.median():+.2f}% 开盘后{ (s.exc5-s.open_premium).median():+.2f}%")

print("\n=== E5. CMMR+右尾：exc5>15%的大赢家名单 ===")
w=t10p['exc5'].dropna()
print(f"  exc5>10%占{(w>10).mean()*100:.0f}% >20%占{(w>20).mean()*100:.0f}%")
big=t10p[t10p.exc5>15].groupby(['code','name']).agg(n=('exc5','size'),best=('exc5','max')).sort_values('best',ascending=False)
print(big.head(15).round(1).to_string())

print("\n=== E6. 连续霸榜衰减 + 隔日回头 ===")
tall = sig.sort_values(['d','cmmrp'],ascending=[True,False]).groupby('d').head(10).copy()
tall['rank']=tall.groupby('d').cumcount()+1
dd=sorted(tall['d'].unique()); codes_p={d:set(g['code']) for d,g in tall.groupby('d')}
runmap={}
for i,d in enumerate(dd):
    newrun={}
    prev = dd[i-1] if i>0 else None
    for c in codes_p[d]:
        newrun[c] = (runmap.get(c,0)+1) if (prev and c in codes_p.get(prev,set())) else 1
    runmap=newrun
    tall.loc[tall.d==d,'run']=tall[tall.d==d]['code'].map(newrun)
rp=add_fwd(tall,hs=(5,))
for k in (1,2,3):
    stat(rp[rp['run']==k]['exc5'], f"CMMR+Top10连续第{k}天")
stat(rp[rp['run']>=4]['exc5'],"连续第4天+")
# 首次上榜但曾在前3-5日出现过（回头票）
hist={}
back=[]
for i,d in enumerate(dd):
    for c in codes_p[d]:
        last=hist.get(c)
        if last is not None:
            gap=i-last
            if 2<=gap<=4: back.append((d,c))
    for c in codes_p[d]: hist[c]=i
bp = rp.merge(pd.DataFrame(back,columns=['d','code']),on=['d','code'],how='inner')
stat(bp['exc5'],"回头票(隔2-4日再上榜)")
# 榜内排位1-3 vs 8-10
stat(rp[rp['rank']<=3]['exc5'],"CMMR+榜内排位1-3")
stat(rp[rp['rank']>=8]['exc5'],"CMMR+榜内排位8-10")

print("\n=== E7. CMMR Top10（cmmr≥80段）exc5 vs cmmrp榜外对照：两榜互补性收益验证（月度组合模拟）===")
# 模拟3种组合每日等权持有5日滚动: 只CMMR榜/只CMMR+榜/两榜各半
def port_sim(pick, name):
    p=add_fwd(pick,hs=(5,))
    p=p.dropna(subset=['exc5'])
    daily=p.groupby('d')['exc5'].mean()
    cum=(1+daily/100).prod()-1
    print(f"  {name}: 日均exc5={daily.mean():+.2f}% 5日复利累计(重叠日简单累乘)={cum:.1%} 负收益日数{(daily<0).sum()}/{len(daily)}")
cset=set(zip(*[t10.d,t10.code])); pset=set(zip(*[t10p.d,t10p.code]))
cm = sig[[ (d,c) in cset for d,c in zip(sig.d,sig.code)]]
pm = sig[[ (d,c) in pset for d,c in zip(sig.d,sig.code)]]
port_sim(cm,"只CMMR Top10")
port_sim(pm,"只CMMR+ Top10")
port_sim(pd.concat([cm,pm]),"两榜各半(20只)")