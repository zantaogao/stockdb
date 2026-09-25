#!/usr/bin/env python3
"""P1+P2 改进回测（只读，不写任何库）
v1 = 现行规则:  CMMR榜=cmmr降序取10（并列内按数据序=实际随机）; CMMR+榜=cmmrp降序取10
v2 = 改进规则:  CMMR榜=cmmr>=80池内按前10日跌幅深->浅取10（并列再用cmmrp打破）
              CMMR+榜=cmmrp降序取10，但剔除"昨天也在v2榜上"的票（P2递归模拟）
评估: 5日前向收益（信号日收盘买入、5交易日后收盘卖出）
  a) 逐日（重叠，描述性） b) 非重叠窗口（严格检验） c) 换手率
"""
import duckdb, pandas as pd, numpy as np
from scipy import stats

con = duckdb.connect('tushare.db', read_only=True)
con.execute("ATTACH 'signals.db' AS sig (TYPE sqlite, READ_ONLY)")

sig = con.execute("""
SELECT REPLACE(date,'-','') d, REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') code,
       stock_name AS "name", cmmr_score cmmr, fusion_score_cmmr cmmrp
FROM sig.signal_history WHERE REPLACE(date,'-','')>='20260728'
""").df()
dl = con.execute("""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, trade_date d, close, pct_chg/100 p
FROM daily WHERE trade_date>='20260601' AND ts_code NOT LIKE '%.BJ'""").df()
cal=sorted(dl['d'].unique()); closes=dl.pivot(index='code',columns='d',values='close')
pcts=dl.pivot(index='code',columns='d',values='p')
mkt=pcts.mean(axis=0)*100; mktcum=(1+mkt/100).cumprod()
mom10 = (closes/closes.shift(10)-1)*100
first={c:closes.loc[c].first_valid_index() for c in closes.index}
sdays=[d for d in sorted(sig['d'].unique())]

def eligible(c,d):
    if c not in closes.index: return False
    if first[c] is None or str(first[c])>'20260715': return False
    v=closes.at[c,d]
    return pd.notna(v) and v>0

def ret5(c,d):
    i=cal.index(d)
    if i+5>=len(cal): return np.nan
    c0,c1=closes.at[c,d],closes.at[c,cal[i+5]]
    if pd.notna(c0) and pd.notna(c1) and abs(c1/c0-1)<2: return (c1/c0-1)*100
    return np.nan

def mkt_ret5(d):
    i=cal.index(d)
    if i+5>=len(cal): return np.nan
    return (mktcum.at[cal[i+5]]/mktcum.at[d]-1)*100

# ---- 逐日构造四份榜单
day_g = {d:g for d,g in sig.groupby('d')}
v1_c, v2_c, v1_p, v2_p = {}, {}, {}, {}
prev_v2c, prev_v2p = set(), set()
for d in sdays:
    g = day_g[d].copy()
    g = g[g['code'].map(lambda c: eligible(c,d))]
    # v1 CMMR: 现行=按cmmr降序（并列按帧序）
    v1_c[d] = list(g.sort_values('cmmr',ascending=False)['code'][:10])
    # v2 CMMR: cmmr>=80池，mom10升序（跌最深优先），并列再按cmmrp降序
    pool = g[g.cmmr>=80].copy()
    pool['m10'] = [mom10.at[c,d] if c in mom10.index and d in mom10.columns else np.nan for c in pool['code']]
    pool = pool.sort_values(['m10','cmmrp'],ascending=[True,False])
    v2_c[d] = list(pool['code'][:10])
    # v1 CMMR+
    v1_p[d] = list(g.sort_values('cmmrp',ascending=False)['code'][:10])
    # v2 CMMR+: 剔除昨日v2榜，顺延补足10
    gg = g[~g['code'].isin(prev_v2p)].sort_values('cmmrp',ascending=False)
    v2_p[d] = list(gg['code'][:10])
    prev_v2c, prev_v2p = set(v2_c[d]), set(v2_p[d])

# 换手率
def turnover(v):
    tots=[]
    ks=[d for d in sdays if v[d]]
    for a,b in zip(ks,ks[1:]):
        # 只算隔一天的（近似日度换手）
        if cal.index(b)-cal.index(a)==1:
            new=set(v[b])-set(v[a]); tots.append(len(new)/len(v[b]))
    return np.mean(tots)*100 if tots else np.nan

print("=== 换手率（相邻交易日榜内新面孔占比均值）===")
for nm,v in [('CMMR v1',v1_c),('CMMR v2',v2_c),('CMMR+ v1',v1_p),('CMMR+ v2',v2_p)]:
    print(f"  {nm}: {turnover(v):.0f}%")

# ---- 逐日组合5日收益（重叠，描述性）
daily = {}
for nm,v in [('CMMR v1',v1_c),('CMMR v2',v2_c),('CMMR+ v1',v1_p),('CMMR+ v2',v2_p)]:
    rows=[]
    for d in sdays:
        rs=[ret5(c,d) for c in v[d]]
        rs=[r for r in rs if pd.notna(r)]
        if rs:
            rows.append({'d':d,'port':np.mean(rs),'exc':np.mean(rs)-mkt_ret5(d),'n':len(rs)})
    daily[nm]=pd.DataFrame(rows)

print("\n=== a) 逐日（重叠持有期，描述性）===")
for nm,df in daily.items():
    t,p = stats.ttest_1samp(df['exc'].clip(-20,30),0)
    cum=(1+df['port']/100).prod()-1
    print(f"  {nm}: n={len(df)} 日均exc={df['exc'].mean():+.2f}% 中位exc={df['exc'].median():+.2f}% 日胜率={(df['exc']>0).mean()*100:.0f}% 简单累乘={cum:.0%} p={p:.3f}")

# ---- 非重叠窗口（严格）
print("\n=== b) 非重叠5日窗口（严格检验，窗口起点每5交易日取一个）===")
nonstart = cal[cal.index('20260728')::5]
nonstart = [d for d in nonstart if d in daily['CMMR v1']['d'].values and not pd.isna(mkt_ret5(d))]
print("窗口起点:", nonstart)
res_tbl=[]
for nm,v in [('CMMR v1',v1_c),('CMMR v2',v2_c),('CMMR+ v1',v1_p),('CMMR+ v2',v2_p)]:
    rs=[]
    for d in nonstart:
        ports=[ret5(c,d) for c in v[d]]
        ports=[r for r in ports if pd.notna(r)]
        if ports: rs.append((d,np.mean(ports)-mkt_ret5(d)))
    s=pd.Series(dict(rs)); res_tbl.append((nm,s))
    print(f"  {nm}: 各窗口exc " + ' '.join(f"{d[4:]}:{r:+.1f}%" for d,r in rs) + f"  | 均值{s.mean():+.2f}% 胜{(s>0).sum()}/{len(s)}")
# 配对检验 v2 vs v1
for (n1,s1),(n2,s2) in [(('CMMR v1',res_tbl[0][1]),('CMMR v2',res_tbl[1][1])),
                         (('CMMR+ v1',res_tbl[2][1]),('CMMR+ v2',res_tbl[3][1]))]:
    common=s1.index.intersection(s2.index)
    if len(common)>=4:
        t,p=stats.ttest_rel(s2[common],s1[common])
        print(f"  配对t({n2} vs {n1}, n={len(common)}): 差值均值{(s2[common]-s1[common]).mean():+.2f}pp p={p:.3f}")

# ---- c) 逐周拆解（重叠但按信号日周分组）
print("\n=== c) 逐周（按信号日分组均值exc）===")
weeks={'W1(7/28-8/1)':('20260728','20260801'),'W2(8/3-7)':('20260803','20260807'),
       'W3(8/10-14)':('20260810','20260814'),'W4(8/17-21)':('20260817','20260821'),
       'W5(8/24-28)':('20260824','20260828')}
hdr=f"{'策略':<10}"+''.join(f"{w:<14}" for w in weeks)
print(hdr)
for nm,df in daily.items():
    line=f"{nm:<10}"
    for w,(a,b) in weeks.items():
        sub=df[(df.d>=a)&(df.d<=b)]
        line+=f"{(str(round(sub.exc.mean(),2))+'%') if len(sub) else '—':<14}"
    print(line)

# ---- v2剔了什么、换来什么（P2明细）
print("\n=== P2明细: CMMR+ v2被剔除的'连续霸榜票'若保留会怎样 ===")
kept_r, cut_r = [], []
prev=set()
for d in sdays:
    gg = day_g[d].copy(); gg = gg[gg['code'].map(lambda c: eligible(c,d))]
    raw = gg.sort_values('cmmrp',ascending=False)
    cut = [c for c in raw['code'][:15] if c in prev]  # 本会被选中的昨日榜票
    for c in cut:
        r=ret5(c,d)
        if pd.notna(r): cut_r.append(r-mkt_ret5(d))
    take = list(gg[~gg['code'].isin(prev)].sort_values('cmmrp',ascending=False)['code'][:10])
    fill_in = [c for c in take if c not in list(raw['code'][:10])]
    for c in fill_in:
        r=ret5(c,d)
        if pd.notna(r): kept_r.append(r-mkt_ret5(d))
    prev=set(v2_p[d])
print(f"  被剔除票(连续第2天) exc5: n={len(cut_r)} 中位={np.median(cut_r):+.2f}%")
print(f"  顶替进场的票        exc5: n={len(kept_r)} 中位={np.median(kept_r):+.2f}%")

# P1明细
print("\n=== P1明细: CMMR v2(深跌优先) vs v1 逐日榜差异规模 ===")
diff = sum(len(set(v1_c[d])^set(v2_c[d])) for d in sdays if v1_c[d] and v2_c[d])
print(f"  20天榜内共 {diff} 人次换位（日均 {diff/len([d for d in sdays if v1_c[d]]):.0f}/20席）")