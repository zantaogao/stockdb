#!/usr/bin/env python3
"""深度第二轮：拆解CMMR三档乘法器 + Top10并列排序 + 尾部驱动 + 隔日重复入场衰减"""
import duckdb, pandas as pd, numpy as np
from scipy import stats

con = duckdb.connect('tushare.db', read_only=True)
con.execute("ATTACH 'signals.db' AS sig (TYPE sqlite, READ_ONLY)")
pd.set_option('display.width', 240)

sig = con.execute("""
SELECT REPLACE(date,'-','') d, REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') code,
 stock_name AS "name", industry, cmmr_score cmmr, fusion_score_cmmr cmmrp,
 old_score, ma40_slope, final_score
FROM sig.signal_history WHERE REPLACE(date,'-','')>='20260801'
""").df()
dl = con.execute("""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, trade_date d, open, close, pre_close, pct_chg/100 p, vol
FROM daily WHERE trade_date>='20260601' AND ts_code NOT LIKE '%.BJ'""").df()
cal=sorted(dl['d'].unique()); closes=dl.pivot(index='code',columns='d',values='close')
opens=dl.pivot(index='code',columns='d',values='open'); pcts=dl.pivot(index='code',columns='d',values='p')
mkt=pcts.mean(axis=0)*100; mktcum=(1+mkt/100).cumprod(); didx={d:i for i,d in enumerate(cal)}
first={c:closes.loc[c].first_valid_index() for c in closes.index}
mom10 = closes.pct_change(10, axis=1, fill_method=None)
volr5 = dl.pivot(index='code',columns='d',values='vol') / dl.pivot(index='code',columns='d',values='vol').rolling(5,axis=1).mean()

# 反推乘法器档位
def mult_of(row):
    if pd.isna(row['ma40_slope']): return np.nan
    if row['ma40_slope']>0.05: return 1.3
    if row['ma40_slope']>0: return 1.0
    if row['ma40_slope']>-0.02: return 0.8
    return 0.5
sig['mult']=sig.apply(mult_of,axis=1)
chk = sig.dropna(subset=['mult'])
chk = chk[chk['mult']>0]
err = (chk['cmmrp'] - chk['old_score']*chk['mult']).abs()
print("乘法器假设验证 cmmrp≈old_score*mult: 中位误差=", round(err.median(),3), " p90误差=", round(err.quantile(.9),3), " 成立率<0.5误差:", round((err<0.5).mean()*100,1),"%")

def add_fwd(df, hs=(1,3,5,10)):
    out=[]
    for _,r in df.iterrows():
        c,d=r['code'],r['d']
        if c not in closes.index: continue
        if first[c] is None or str(first[c])>'20260715': continue
        i=didx[d]; rec=dict(r)
        for h in hs:
            if i+h<len(cal):
                c0,c1=closes.at[c,d],closes.at[c,cal[i+h]]
                if pd.notna(c0) and pd.notna(c1) and c0>0 and abs(c1/c0-1)<1.5:
                    rec[f'fwd{h}']=(c1/c0-1)*100
                    rec[f'exc{h}']=rec[f'fwd{h}']-(mktcum.at[cal[i+h]]/mktcum.at[d]-1)*100
            # 次日开盘溢价（信号日收盘->次日开盘）
            if h==1:
                o=opens.at[c,cal[i+1]] if i+1<len(cal) else np.nan
                if pd.notna(c0) and pd.notna(o): rec['open_premium']=(o/c0-1)*100
        if d in mom10.columns and c in mom10.index:
            m=mom10.at[c,d]
            if pd.notna(m): rec['mom10']=m*100
        if c in volr5.index and d in volr5.columns:
            v=volr5.at[c,d]
            if pd.notna(v): rec['volr']=v
        out.append(rec)
    return pd.DataFrame(out)

def stat(s,label):
    s=pd.Series(s).dropna()
    if len(s)<10: print(f"  {label}: n={len(s)} 样本不足"); return
    t,p=stats.ttest_1samp(s.clip(-20,30),0)
    print(f"  {label}: n={len(s)} 中位={s.median():+.2f}% 胜率={(s>0).mean()*100:.0f}% p={p:.3f}")

print("\n=== E1. CMMR+拆解：old_score十分位 × 乘法器档位 → exc10中位 ===")
e1 = add_fwd(sig.dropna(subset=['old_score','mult']).sample(9000,random_state=5), hs=(10,))
e1['os_dec']=pd.qcut(e1['old_score'],10,labels=False,duplicates='drop')
piv = e1.pivot_table(index='os_dec',columns='mult',values='exc10',aggfunc='median')
cnt = e1.pivot_table(index='os_dec',columns='mult',values='exc10',aggfunc='size')
print("exc10中位:"); print(piv.round(2).to_string())
print("n:"); print(cnt.to_string())

print("\n=== E2. old_score本身十分位 → exc5/exc10（百分位分有没有信息）===")
e2 = e1.groupby('os_dec').agg(n=('exc10','size'),中位exc10=('exc10','median'),胜率=('exc10',lambda s:(s.clip(-20,30)>0).mean()*100))
print(e2.round(2).to_string())
print("  old_score十分位 vs reg融合分排序一致性: 注意old_score=当日百分位(0-100均匀分布)")

print("\n=== E3. 乘法器有效吗：同一old_score百分位带内比较不同mult ===")
for lo,hi,lab in [(90,101,'old_score>90'),(70,90,'70-90'),(50,70,'50-70')]:
    band=e1[(e1.old_score>=lo)&(e1.old_score<hi)]
    for m_ in (1.3,1.0,0.8,0.5):
        stat(band[band['mult']==m_]['exc10'], f"{lab} mult={m_}")
    print()

print("=== E4. CMMR Top10并列破解：cmmr=100分每日几只？Top10是并列内怎么排的（按mom10/市值重排有没有用）===")
c100 = sig[sig.cmmr>=100].groupby('d').size()
print("cmmr=100每日只数:", c100.to_dict())
t10 = sig.sort_values('cmmr',ascending=False).groupby('d').head(10)
t10b = add_fwd(t10, hs=(1,5,10))
# 并列内按10日跌幅最深排 vs 最浅排
for asc_, lab in [(True,'并列内选跌最深'),(False,'并列内选跌最浅')]:
    pick = sig[sig.cmmr>=80].sort_values(['d','mom10'],ascending=[True,asc_]).groupby('d').head(6)
    pb = add_fwd(pick, hs=(5,))
    stat(pb['exc5'], lab)
print("  Top10票开盘溢价（信号日收盘->次日开盘，=能不能上车）:")
for nm,q in [('CMMR',t10b)]:
    print(f"   {nm}: 次日开盘溢价中位 {q['open_premium'].median():+.2f}%, 开盘即高开>2%占比 {(q['open_premium']>2).mean()*100:.0f}%")
t10p = add_fwd(sig.sort_values('cmmrp',ascending=False).groupby('d').head(10), hs=(1,5,10))
print(f"   CMMR+: 次日开盘溢价中位 {t10p['open_premium'].median():+.2f}%, 高开>2%占比 {(t10p['open_premium']>2).mean()*100:.0f}%")

print("\n=== E5. CMMR+右尾驱动：exc5>+10%的大赢家有多少只票贡献？===")
w = t10p['exc5'].dropna()
print("exc5分位:", w.quantile([.5,.75,.9,.95]).round(1).to_dict())
print(f"exc5>10%占{(w>10).mean()*100:.0f}%, >20%占{(w>20).mean()*100:.0f}%")
top_w = t10p[t10p.exc5>15].groupby(['code','name']).size().sort_values(ascending=False)
print("大赢家(单次exc5>15%)出现次数:", top_w.head(12).to_dict())

print("\n=== E6. 隔日重复信号衰减曲线：连续N天在Top10的第k天表现 ===")
tall_p = sig.sort_values(['d','cmmrp'],ascending=[True,False]).groupby('d').head(10).copy()
tall_p['rank']=tall_p.groupby('d').cumcount()+1
run=[]
seen={}
for d,g in tall_p.groupby('d'):
    for _,r in g.iterrows():
        k = seen.get(r['code'],0)+1; seen[r['code']]=k
        # 中断即重置：如果k-1那天该票不在昨天Top10则重置——简化：用连续日检查
        run.append((d,r['code'],k))
tall_p['run']=[k for _,_,k in run]
rp = add_fwd(tall_p, hs=(5,))
for k in (1,2,3,4):
    sub = rp[rp['run']==k] if k<4 else rp[rp['run']>=4]
    stat(sub['exc5'], f"CMMR+ Top10连续第{k}{'+' if k==4 else ''}天")
# 隔天再来（非连续，间隔1-3天重复上榜）
codes_p = {d:set(g['code']) for d,g in tall_p.groupby('d')}
dd=list(sig['d'].sort_values().unique())
gap_stats={'间隔2-3天回头':[]}
for i,d in enumerate(dd):
    if i<4: continue
    for c in codes_p[d]:
        prev_days=[dd[j] for j in range(max(0,i-3),i) if c in codes_p.get(dd[j],())]
        had4 = c in codes_p.get(dd[max(0,i-4)],())
        if prev_days and not had4:
            gap_stats['间隔2-3天回头'].append((d,c))
gp = rp.merge(pd.DataFrame(gap_stats['间隔2-3天回头'],columns=['d','code']),on=['d','code'])
stat(gp['exc5'],"间隔2-3天回头上榜")

print("\n=== E7. 趋势档位对reg分的放大是否方向正确：mult=1.3且old>90的票 mom10画像 ===")
band=e1[(e1.old_score>=90)]
for m_ in (1.3,1.0,0.8,0.5):
    s2=band[band['mult']==m_]
    if len(s2)>=10:
        print(f"  mult={m_}: n={len(s2)} mom10中位={s2['mom10'].median():+.1f}% exc10中位={s2['exc10'].median():+.2f}% 胜率={(s2.exc10.clip(-20,30)>0).mean()*100:.0f}%")