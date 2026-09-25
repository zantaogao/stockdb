#!/usr/bin/env python3
"""流水审查第二轮：T1b金额差异定性 T5时间 T6持仓连续性 T7现金 T8信号分追溯 T9当日新单"""
import sqlite3, duckdb, pandas as pd, numpy as np, json, os

led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
pd.set_option('display.width', 240); pd.set_option('display.max_rows', 300)
tl = pd.read_sql("SELECT rowid rid, * FROM trade_log", led)
tl['dn']=tl['trade_date'].str.replace('-','',regex=False)
tl['tn']=tl['trade_time'].astype(str).str.extract(r'(\d{2}):?(\d{2})?')[0].fillna('') + tl['trade_time'].astype(str).str.extract(r'\d{2}:?(\d{2})')[0].fillna('')
tl['hhmm'] = tl['trade_time'].astype(str).str.replace(':','',regex=False).str[:4]

print("=== T1b 金额差异定性（92条 amount≠价×量）===")
tl['pxq']=tl['price']*tl['quantity']; tl['diff']=tl['amount']-tl['pxq']
d = tl[tl['diff'].abs()>0.51].copy()
d['rate']=d['diff']/d['pxq']*10000  # 万分之
print("BUY差异为正(含费):", (d[d.direction=='BUY']['diff']>0).sum(), "/", (d.direction=='BUY').sum())
print("SELL差异为负(扣费):", (d[d.direction=='SELL']['diff']<0).sum(), "/", (d.direction=='SELL').sum())
print("差异费率(万分比)分布: 中位", round(d['rate'].abs().median(),1), "p95", round(d['rate'].abs().quantile(.95),1), "最大", round(d['rate'].abs().max(),1))
print("→ 若费率集中在1-3‱=手续费口径混入amount(可解释)；无fee表的口径混用")
same = tl[tl['diff'].abs()<=0.51]
print("对照：净额记录(amount=价×量)条数:", len(same), " 按策略:", same.groupby(tl['strategy'].fillna('(NULL)')).size().to_dict())

print("\n=== T1c strategy=NULL 的27条是谁的账？===")
nul = tl[tl['strategy'].isna()]
main_buy_dates = set(tl[tl['strategy']=='main']['dn'])
print(nul.groupby(['dn','direction']).size().to_dict())
print("NULL记录是否都能对上主账户持仓变化窗口(8/18-8/25):", nul['dn'].between('20260818','20260825').mean())

print("\n=== T1d 今日(8/31)记录名缺失 ===")
today = tl[tl['dn']=='20260831']
print("今日记录:", len(today), "名字缺失:", today['name'].isna().sum() | (today['name'].astype(str).str.strip()=='').sum())
print(today[['rid','code','name','direction','price','quantity','trade_time','strategy']].to_string(index=False))

print("\n=== T5 时间合规 ===")
con = duckdb.connect('tushare.db', read_only=True)
tbad = tl[(tl['hhmm'].str.len()==4) & (~((tl['hhmm']>='0930')&(tl['hhmm']<='1130')) & ~((tl['hhmm']>='1300')&(tl['hhmm']<='1500')))]
print("非交易时段:", len(tbad))
if len(tbad): print(tbad[['rid','dn','trade_time','code','direction','strategy']].to_string(index=False))
print("trade_time缺失8条:", tl[tl['trade_time'].isna()|(tl['trade_time'].astype(str).str.len()<3)]['rid'].tolist(),
      tl[tl['trade_time'].isna()|(tl['trade_time'].astype(str).str.len()<3)][['rid','dn','code','direction','strategy','notes']].head(10).to_string(index=False))

print("\n=== T6 持仓连续性回放（每策略逐笔，超卖=T+1违规或漏记）===")
hold = pd.read_sql("SELECT code, shares FROM holdings", led)
spos = pd.read_sql("SELECT account_id, code, shares FROM strategy_positions", led)
issues=[]
for strat, g in tl.groupby(tl['strategy'].fillna('(NULL)')):
    g=g.assign(t2=g['trade_time'].astype(str)).sort_values(['dn','t2','rid'])
    pos={}
    for _,r in g.iterrows():
        c=r['code']; d_=r['direction'].upper()
        if d_=='BUY': pos[c]=pos.get(c,0)+r['quantity']
        else:
            h=pos.get(c,0)
            if r['quantity']>h: issues.append((strat,r['dn'],c,r['quantity'],h))
            pos[c]=h-r['quantity']
    final_hold = dict(zip(hold['code'],hold['shares'])) if strat in ('main','(NULL)') else dict(zip(spos[spos.account_id==strat]['code'],spos[spos.account_id==strat]['shares']))
    # main与NULL合并才是主账户真身——分开回放假阳性，合并版下面单独跑
    if strat in ('main','(NULL)'): continue
    diff={c:(pos.get(c,0),final_hold.get(c,0)) for c in set(pos)|set(final_hold) if pos.get(c,0)!=final_hold.get(c,0)}
    print(f"  [{strat}] 回放期末vs DB持仓 差异{len(diff)}只", dict(list(diff.items())[:10]))
m = tl[tl['strategy'].isin(['main'])|tl['strategy'].isna()].assign(t2=lambda x:x['trade_time'].astype(str)).sort_values(['dn','t2','rid'])
pos={}
for _,r in m.iterrows():
    c=r['code']
    pos[c]=pos.get(c,0)+(r['quantity'] if r['direction'].upper()=='BUY' else -r['quantity'])
diff={c:(pos.get(c,0),int(hold[hold.code==c]['shares'].iloc[0]) if (hold.code==c).any() else 0) for c in set(pos)|set(hold['code']) if pos.get(c,0)!=int(hold[hold.code==c]['shares'].iloc[0]) if (hold.code==c).any() or pos.get(c,0)!=0}
print(f"  [main+NULL合并] 期末vs holdings 差异{len(diff)}只: {dict(list(diff.items())[:12])}")
print("  (08-20漏记8笔卖出在白名单，差异应集中在那8只)")
print("  超卖异常:", issues if issues else "无")

print("\n=== T7 现金回放 vs account_balance/meta.cash ===")
ab = pd.read_sql("SELECT * FROM account_balance", led)
snap=json.load(open('sim_accounts/main.json')) if os.path.exists('sim_accounts/main.json') else None
mm = tl[tl['strategy'].isin(['main'])|tl['strategy'].isna()]
print("account_balance: cash=", round(ab['cash_balance'].iloc[0]), "total=", round(ab['total_value'].iloc[0]), "更新:", ab['last_update'].iloc[0])
if snap and 'positions' in snap:
    c0=snap['cash']; delta=mm[mm['dn']>'20260803'].apply(lambda r:(-r['amount'] if r['direction']=='BUY' else r['amount']),axis=1).sum()
    print(f"8/3快照现金{c0:,.0f}+流水净额{delta:+,.0f}={c0+delta:,.0f} vs 当前{ab['cash_balance'].iloc[0]:,.0f} 差{ab['cash_balance'].iloc[0]-c0-delta:+,.0f}")
meta = pd.read_sql("SELECT * FROM strategy_accounts_meta", led)
for _,mr in meta.iterrows():
    g=tl[tl['strategy']==mr['account_id']]
    delta=g.apply(lambda r:(-r['amount'] if r['direction']=='BUY' else r['amount']),axis=1).sum()
    est=mr['initial_capital']+delta
    print(f"  [{mr['account_id']}] 初始{mr['initial_capital']/1e4:.0f}万+流水{delta/1e4:+.1f}万={est/1e4:.1f}万 vs cash{mr['cash']/1e4:.1f}万 差{(mr['cash']-est)/1e4:+.1f}万")
print("  (差≈持仓市值时说明cash字段=总资产口径而非现金，看正负号定论)")

print("\n=== T8 买入票当日信号分追溯 ===")
sig = pd.read_sql("""SELECT REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') code, REPLACE(date,'-','') d,
 cmmr_score, fusion_score_cmmr FROM signal_history WHERE REPLACE(date,'-','')>='20260720'""", sqlite3.connect('file:signals.db?mode=ro',uri=True))
buy = tl[tl['direction']=='BUY'].merge(sig, left_on=['code','dn'], right_on=['code','d'], how='left')
sell = tl[tl['direction']=='SELL'].merge(sig, left_on=['code','dn'], right_on=['code','d'], how='left')
for s_,g in buy.groupby(buy['strategy'].fillna('(NULL)')):
    if s_ in ('main','(NULL)'): continue
    cov=g['fusion_score_cmmr'].notna().mean()
    print(f"  BUY[{s_}]: n={len(g)} 有分率{cov*100:.0f}% cmmrp中位{g['fusion_score_cmmr'].median():.1f} <50分买入占{(g['fusion_score_cmmr']<50).mean()*100:.0f}%")
for s_,g in sell.groupby(sell['strategy'].fillna('(NULL)')):
    if s_ in ('main','(NULL)'): continue
    hi=(g['fusion_score_cmmr']>=80).sum()
    print(f"  SELL[{s_}]: n={len(g)} 中位{g['fusion_score_cmmr'].median():.1f} 高分(≥80)卖出{hi}笔")
print("\n=== T8b 无日线记录即成交（成交日行情缺失）: 前轮=0 复查8/31 ===")
t31=tl[tl['dn']=='20260831']
d31=con.execute("SELECT COUNT(*) FROM daily WHERE trade_date='20260831'").fetchone()[0]
print(f"8/31 daily行数={d31}（盘中成交，日线路径正常滞后）")