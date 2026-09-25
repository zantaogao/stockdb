#!/usr/bin/env python3
"""8月 CMMR/CMMR+ 深度挖掘：
D1. cmmr分数离散结构（12档组合）各档前向收益 —— Top10排序实际在排什么
D2. cmmrp = f(cmmr, fusion) 反推公式验证
D3. 趋势×超卖交叉：CMMR高分票是'上涨回调'还是'下跌反抽'
D4. 条件IC：cmmr/cmmrp对reg模型分的增量信息（偏相关）
D5. 分数膨胀根因：各档位占比逐日演变（市场宽度时序）
D6. 8/19暴跌日前后信号表现（抄底时机）
D7. 策略账户实盘净值曲线与回撤，对比等权信号回测
"""
import duckdb, pandas as pd, numpy as np
from scipy import stats

con = duckdb.connect('tushare.db', read_only=True)
con.execute("ATTACH 'signals.db' AS sig (TYPE sqlite, READ_ONLY)")
con.execute("ATTACH 'ledger.db' AS led (TYPE sqlite, READ_ONLY)")
pd.set_option('display.width', 240)

sig = con.execute("""
SELECT REPLACE(date,'-','') d, REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') code,
       stock_name AS "name", industry, cmmr_score cmmr, fusion_score_cmmr cmmrp,
       reg10, reg20, reg40, fusion_score, old_score, final_score, ma40_slope
FROM sig.signal_history WHERE REPLACE(date,'-','')>='20260801'
""").df()
dl = con.execute("""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, trade_date d, close, pct_chg/100 p
FROM daily WHERE trade_date>='20260601' AND ts_code NOT LIKE '%.BJ'""").df()
cal = sorted(dl['d'].unique()); closes = dl.pivot(index='code',columns='d',values='close')
pcts = dl.pivot(index='code',columns='d',values='p')
mkt = pcts.mean(axis=0)*100; mktcum=(1+mkt/100).cumprod(); didx={d:i for i,d in enumerate(cal)}
first = {c: closes.loc[c].first_valid_index() for c in closes.index}

# 10日动量（信号日回溯）用于D3
mom10 = closes.pct_change(10, axis=1)

def add_fwd(df, hs=(3,5,10)):
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
        # 回溯动量
        if d in mom10.columns and c in mom10.index:
            m=mom10.at[c,d]
            if pd.notna(m): rec['mom10']=m*100
        out.append(rec)
    return pd.DataFrame(out)

def stat(s, label):
    s=pd.Series(s).dropna()
    if len(s)<10: print(f"  {label}: n={len(s)} (样本不足)"); return
    t,p=stats.ttest_1samp(s.clip(-20,30),0)
    print(f"  {label}: n={len(s)} 中位={s.median():+.2f}% 胜率={(s>0).mean()*100:.0f}% t={t:.2f} p={p:.3f}")

print("="*70)
print("D1. cmmr离散档位结构（总分=趋势0/20/40+超卖0/20/40+量能0/20）各档前向表现")
big = add_fwd(sig[sig['cmmr']>0], hs=(5,10))
big['grade']=big['cmmr'].astype(int).astype(str)
g=big.groupby('grade').agg(n=('exc5','size'),中位exc5=('exc5','median'),中位exc10=('exc10','median'),
    exc5胜率=('exc5',lambda s:(s.clip(-20,30)>0).mean()*100))
print(g[g['n']>=10].round(2).to_string())

print()
print("D2. cmmrp公式反推（cmmrp vs cmmr*fusion的关系）")
samp = sig.dropna(subset=['cmmrp','fusion_score']).sample(3000, random_state=1)
samp['prod']=samp['cmmr']*samp['fusion_score']/100
samp['sum_']=(samp['cmmr']+samp['fusion_score'])/2
print("  corr(cmmrp, cmmr*fusion/100) =", round(samp['cmmrp'].corr(samp['prod']),4))
print("  corr(cmmrp, (cmmr+fusion)/2) =", round(samp['cmmrp'].corr(samp['sum_']),4))
samp['ratio']=samp['cmmrp']/samp['prod'].replace(0,np.nan)
print("  cmmrp/(cmmr*fus/100) 比值分布:", samp['ratio'].describe()[['mean','std','min','max']].round(3).to_dict())

print()
print("D3. CMMR高分票画像：mom10(信号前10日动量)分组 × exc5")
t10 = sig.sort_values('cmmr',ascending=False).groupby('d').head(10)
t10b = add_fwd(t10, hs=(5,))
t10b['mb']=pd.cut(t10b['mom10'],[-100,-15,-8,-4,0,4,8,15,100],labels=['<-15','-15~-8','-8~-4','-4~0','0~4','4~8','8~15','>15'])
print(t10b.groupby('mb',observed=True).agg(n=('exc5','size'),中位exc5=('exc5','median'),胜率=('exc5',lambda s:(s.clip(-20,30)>0).mean()*100)).round(2).to_string())
print("  CMMR Top10 mom10中位数:", round(t10b['mom10'].median(),1),"%  |  CMMR+ Top10:")
t10p = add_fwd(sig.sort_values('cmmrp',ascending=False).groupby('d').head(10), hs=(5,))
print("  mom10中位数:", round(t10p['mom10'].median(),1),"%  mom10分组:")
t10p['mb']=pd.cut(t10p['mom10'],[-100,-15,-8,-4,0,4,8,15,100],labels=['<-15','-15~-8','-8~-4','-4~0','0~4','4~8','8~15','>15'])
print(t10p.groupby('mb',observed=True).agg(n=('exc5','size'),中位exc5=('exc5','median'),胜率=('exc5',lambda s:(s.clip(-20,30)>0).mean()*100)).round(2).to_string())

print()
print("D4. 条件/偏相关IC：cmmr与cmmrp对reg模型分有无增量信息（exc10为y）")
cond = add_fwd(sig.sample(8000, random_state=3), hs=(10,))
cond = cond.dropna(subset=['exc10','cmmr','cmmrp','fusion_score'])
def partial_ic(x, ctrl_vars, y):
    sub = cond.dropna(subset=[x]+ctrl_vars+[y])
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(sub))]+[sub[c] for c in ctrl_vars])
    beta = lstsq(X, sub[y], rcond=None)[0]
    resid_y = sub[y] - X@beta
    X2 = np.column_stack([np.ones(len(sub))]+[sub[c] for c in ctrl_vars])
    resid_x = sub[x] - X2@lstsq(X2, sub[x], rcond=None)[0]
    return stats.spearmanr(resid_x, resid_y).statistic, len(sub)
for x in ('cmmr','cmmrp'):
    for ctrl in (['fusion_score'],['fusion_score','cmmr'],['fusion_score','reg10','reg20','reg40']):
        cc = [c for c in ctrl if c!=x]
        if not cc: continue
        try:
            r,n = partial_ic(x, cc, 'exc10')
            print(f"  偏IC({x} | {'+'.join(cc)}) = {r:+.3f}  n={n}")
        except Exception as e: print("  ",x,ctrl,"fail",e)
# 对照：无条件
for x in ('cmmr','cmmrp','fusion_score'):
    sub=cond[[x,'exc10']].dropna()
    print(f"  无条件IC({x}) = {stats.spearmanr(sub[x],sub.exc10).statistic:+.3f}")

print()
print("D5. 分数膨胀根因：cmmr各档位占比逐日 + 与市场宽度对照")
piv = sig.assign(g=lambda x: pd.cut(x['cmmr'],[-0.1,19.9,39.9,59.9,79.9,100.1],labels=['0','20','40','60','80-100'],ordered=False))
share = pd.crosstab(piv['d'], piv['g'], normalize='index').mul(100).round(2)
breadth = {}
for d in sorted(set(sig['d'])):
    m = pcts[d] if d in pcts.columns else None
    if m is not None:
        i=didx[d]
        if i>=10:
            past = pcts.loc[:, cal[i-9]:cal[i]].sum(axis=1)*100
            breadth[d] = round((past>-4).mean()*100,1)  # 10日跌幅超4%的票占比的反面
share['超卖票占比%'] = pd.Series(breadth)
share['当日大盘%'] = pd.Series({d: round(mkt[d],2) for d in share.index})
print(share.to_string())

print()
print("D6. 8/19暴跌日(大盘-4.02%)专项：暴跌日 vs 前一日 vs 后一日发的Top10 exc5/exc10")
tall = pd.concat([
    sig[sig.d=='20260818'].sort_values('cmmr',ascending=False).head(10).assign(s='CMMR',day='8/18(暴跌前)'),
    sig[sig.d=='20260819'].sort_values('cmmr',ascending=False).head(10).assign(s='CMMR',day='8/19(暴跌日)'),
    sig[sig.d=='20260820'].sort_values('cmmr',ascending=False).head(10).assign(s='CMMR',day='8/20(暴跌后)'),
    sig[sig.d=='20260818'].sort_values('cmmrp',ascending=False).head(10).assign(s='CMMR+',day='8/18(暴跌前)'),
    sig[sig.d=='20260819'].sort_values('cmmrp',ascending=False).head(10).assign(s='CMMR+',day='8/19(暴跌日)'),
    sig[sig.d=='20260820'].sort_values('cmmrp',ascending=False).head(10).assign(s='CMMR+',day='8/20(暴跌后)'),
])
tall=add_fwd(tall,hs=(5,10))
for (s,day),g in tall.groupby(['s','day']):
    stat(g['exc5'], f"{s} {day} exc5")

print()
print("D7. 实盘vs信号回测：cmmr/cmmr_fusion账户逐日NAV vs 当日信号日收益")
nav = con.execute("""SELECT account_id, REPLACE(date,'-','') d, nav, n_pos FROM led.strategy_accounts_legacy
 WHERE account_id IN ('cmmr','cmmr_fusion') AND REPLACE(date,'-','')>='20260801' ORDER BY d""").df()
if len(nav):
    for a,g in nav.groupby('account_id'):
        g=g.sort_values('d'); g['ret']=(g['nav'].pct_change()*100).round(2)
        worst = g['nav']/g['nav'].cummax()-1
        print(f"  {a}: 区间{g['d'].iloc[0]}-{g['d'].iloc[-1]} 收益{(g['nav'].iloc[-1]/g['nav'].iloc[0]-1)*100:+.1f}% 最大回撤{worst.min()*100:.1f}% 负收益天数{(g['ret']<0).sum()}/{g['ret'].notna().sum()}")
bt = con.execute("SELECT * FROM sig.cmmr_backtest ORDER BY signal_date").df()
if len(bt):
    bt['d']=bt['signal_date'].str.replace('-','',regex=False)
    print("\n  cmmr_backtest表(等权信号回测, fwd收益%):")
    print(bt[['d','cmmr_ew','cmmr_win','cmmr80_ew','fsc_ew','fsc_win','mkt_ew']].round(2).to_string(index=False))