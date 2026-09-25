#!/usr/bin/env python3
"""交易流水全面审查（只读，不写库）
T1 格式健康：日期/时间格式混存、方向大小写、金额=价×量一致性
T2 重复记录：同日同票同价同量同方向
T3 价格合规：成交价 vs 当日真实最高/最低/涨跌停价（超界=假成交）
T4 数量合规：科创板/创业板买入<200股、非整手（卖出零碎除外）
T5 时间合规：非交易时段成交（9:30-11:30/13:00-15:00外）、非交易日
T6 持仓连续性：卖出量>当时持股、卖光后又卖、卖出未平仓又现持仓
T7 现金自洽：逐笔回放 vs account_balance（main），策略账户 vs meta.cash
T8 信号分追溯：成交票成交日信号分分布（买低分/卖高分的异常）
T9 跨账本对账：策略账户trade_log重建持仓 vs strategy_positions
"""
import sqlite3, duckdb, pandas as pd, numpy as np

led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
pd.set_option('display.width', 240); pd.set_option('display.max_rows', 200)

tl = pd.read_sql("SELECT rowid rid, * FROM trade_log", led)
tl['dn'] = tl['trade_date'].str.replace('-','',regex=False)
tl['tn'] = tl['trade_time'].astype(str).str.replace(':','',regex=False).str[:6]
print(f"流水总数 {len(tl)}，字段: {[c for c in tl.columns if c not in ('rid','dn','tn')]}")
print(f"日期范围 {tl.dn.min()} - {tl.dn.max()}；策略分布: {tl['strategy'].fillna('(NULL)').value_counts().to_dict()}")

print("\n=== T1 格式健康 ===")
print("日期带横线格式条数:", (tl['trade_date'].str.contains('-')).sum(),
      "| 分布(按策略):", tl[tl['trade_date'].str.contains('-')].groupby(tl['strategy'].fillna('(NULL)')).size().to_dict())
print("direction取值:", tl['direction'].value_counts().to_dict())
bad_amt = tl[(tl.price*tl-quantity_ if False else tl.amount - tl.price*tl.quantity).abs() > 0.51]
print("amount≠price×qty(>0.5元)条数:", len(bad_amt))
if len(bad_amt): print(bad_amt[['rid','code','name','direction','price','quantity','amount','dn','strategy']].to_string(index=False))
print("price或qty缺失:", tl[['price','quantity','amount']].isna().sum().to_dict())
print("trade_time缺失/异常:", (tl['trade_time'].isna() | (tl['tn']=='')).sum(), "条")

print("\n=== T2 重复记录（同日同票同向同价同量）===")
dup = tl[tl.duplicated(subset=['dn','code','direction','price','quantity'], keep=False) & tl.dn.ge('20260815')].sort_values(['dn','code'])
# 历史补录允许同笔重复？先分开看
print("8/15后重复组:", dup.groupby(['dn','code','direction','price','quantity','strategy']).size().to_dict() if len(dup) else "无")
dup_all = tl[tl.duplicated(subset=['dn','code','direction','price','quantity','strategy'], keep=False)]
print("全时段完全重复(含策略):", len(dup_all), "条 →", dup_all['dn'].value_counts().head(8).to_dict() if len(dup_all) else '')

print("\n=== T3 价格合规（成交价越界=假成交）===")
con = duckdb.connect('tushare.db', read_only=True)
codes = list(tl['code'].unique())
ph = ','.join("'"+c+"'" for c in codes)
mk = con.execute(f"""
SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') code, trade_date d, open, high, low, close, pre_close,
       round(pre_close*1.2,2) lu_main, round(pre_close*1.1,2) lu_main10
FROM daily WHERE trade_date IN (SELECT DISTINCT REPLACE(REPLACE(trade_date,'-',''),'-','') FROM daily)
AND trade_date BETWEEN '20260601' AND '20260901'
AND REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') IN ({ph})""").df()
mk['d']=mk['d'].str.replace('-','',regex=False)
m = tl.merge(mk, left_on=['code','dn'], right_on=['code','d'], how='left', suffixes=('','_m'))
m['hi_limit'] = np.where(m['code'].str.startswith(('300','301','688')), m['pre_close']*1.2, m['pre_close']*1.1)
m['lo_limit'] = np.where(m['code'].str.startswith(('300','301','688')), m['pre_close']*0.8, m['pre_close']*0.9)
# ST股5%：先标记再看
no_daily = m[m['close'].isna()]
print("成交日无日线数据(停牌/日期错?):", len(no_daily))
if len(no_daily): print(no_daily[['rid','dn','code','name','direction','price','strategy']].head(15).to_string(index=False))
above = m[(m['close'].notna()) & (m['price'] > m['hi_limit']*1.001)]
below = m[(m['close'].notna()) & (m['price'] < m['lo_limit']*0.999)]
outside_hl = m[(m['close'].notna()) & ((m['price'] > m['high']*1.001) | (m['price'] < m['low']*0.999))]
print(f"价越涨跌停: 高{len(above)} 低{len(below)}；价越当日高低区间: {len(outside_hl)}")
for lab, sub in [('越涨停上界',above),('越跌停下界',below)]:
    if len(sub): print(lab); print(sub[['rid','dn','code','name','direction','price','close','high','low','hi_limit','strategy']].head(20).to_string(index=False))

print("\n=== T4 数量合规（科创/创业板买<200股）===")
buy = tl[tl['direction'].str.upper()=='BUY']
small = buy[buy['code'].str.startswith(('300','301','688')) & (buy['quantity']<200)]
print("科创/创业板买入<200股:", len(small), "条")
if len(small): print(small[['rid','dn','code','name','quantity','price','strategy']].to_string(index=False))
odd = buy[buy['quantity']%100!=0]
print("买入非整手:", len(odd))
if len(odd): print(odd[['rid','dn','code','name','quantity','strategy']].head(15).to_string(index=False))

print("\n=== T5 时间合规 ===")
trading_days = set(r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date BETWEEN '20260601' AND '20260901'").fetchall())
off = tl[~tl['dn'].isin(trading_days)]
print("非交易日成交:", len(off))
if len(off): print(off[['rid','trade_date','code','direction','strategy']].head(10).to_string(index=False))
tbad = tl[(tl['tn']!='') & (((tl['tn']>='093000'&tl['tn']<='113000')==False) & ((tl['tn']>='130000'&tl['tn']<='150000')==False))]
print("非交易时段成交(有无时间都算):", len(tbad))
if len(tbad): print(tbad[['rid','trade_date','trade_time','code','direction','strategy']].head(20).to_string(index=False))

print("\n=== T6 持仓连续性回放（逐票按时间：卖出不得超持有；期末 vs holdings/strategy_positions）===")
hold = pd.read_sql("SELECT code, shares FROM holdings", led)
hmap = dict(zip(hold['code'], hold['shares']))
spos = pd.read_sql("SELECT account_id, code, shares FROM strategy_positions", led)
acc_final = {}
for _,r in spos.iterrows(): acc_final[(r['account_id'],r['code'])] = r['shares']
prob=[]
tl_sorted = tl.sort_values(['dn', tl['tn'] if 'tn' in tl else 'rid'] if False else ['dn'])
for strat, g in tl.groupby(tl['strategy'].fillna('(NULL)')):
    pos={}
    g = g.assign(tn2=g['trade_time'].astype(str)).sort_values(['dn','tn2'])
    for _,r in g.iterrows():
        d = r['direction'].upper(); c=r['code']
        if d=='BUY': pos[c]=pos.get(c,0)+r['quantity']
        elif d=='SELL':
            held=pos.get(c,0)
            if r['quantity']>held:
                prob.append((strat,r['dn'],c,r['name'],r['quantity'],held,'超卖'))
            pos[c]=held-r['quantity']
    if strat=='(NULL)' or strat=='main':
        final_check = hmap
    else:
        final_check = {c:v for (a,c),v in acc_final.items() if a==strat}
    # 只报期末差异大的
    diff = {c:(pos.get(c,0), final_check.get(c,0)) for c in set(pos)|set(final_check) if abs(pos.get(c,0)-final_check.get(c,0))>0 and pos.get(c,0)!=final_check.get(c,0)}
    # 试仓100股噪声排除后输出
    if diff:
        big = {c:v for c,v in diff.items()}
        print(f"  [{strat}] 回放期末 vs 当前持仓 不一致 {len(big)} 只: { {c:v for c,v in list(big.items())[:15]} }")
print("  超卖异常:", len(prob), prob[:10] if prob else '')

print("\n=== T7 现金自洽（main: 08-03快照+流水回放 vs account_balance）===")
ab = pd.read_sql("SELECT * FROM account_balance", led)
print("account_balance:", ab[['cash_balance','total_value','last_update']].to_dict('records'))
import json, os
snap_p = 'sim_accounts/main.json'
if os.path.exists(snap_p):
    snap=json.load(open(snap_p))
    if 'positions' in snap:
        cash0 = snap.get('cash'); tc0 = sum(p.get('total_cost', p['shares']*p.get('avg_cost',0)) for p in snap['positions'])
        mn = tl[(tl['strategy'].fillna('main').isin(['main','(NULL)']))]
        mn = mn[mn['dn']>='20260804']
        delta = mn.apply(lambda r: (-r['amount'] if r['direction'].upper()=='BUY' else r['amount']), axis=1).sum()
        est_cash = cash0 + delta
        print(f"快照现金{cash0:.0f} + 流水净额{delta:+.0f} = {est_cash:.0f} vs 当前{ab['cash_balance'].iloc[0]:.0f} 差{ab['cash_balance'].iloc[0]-est_cash:+.0f}")
        print("（已知缺口：08-20漏记8笔卖出≈15.5万，白名单口径）")
    else:
        print("main.json 结构变化，跳过快照对账")
else:
    print("sim_accounts/main.json 不存在，跳过")
# 策略账户现金
meta = pd.read_sql("SELECT * FROM strategy_accounts_meta", led)
for _,mrow in meta.iterrows():
    g = tl[tl['strategy']==mrow['account_id']]
    g = g[g['dn']>=(mrow['created_at'] or '')[:10].replace('-','') if mrow['created_at'] else g['dn']>='20260101']
    delta = g.apply(lambda r: (-r['amount'] if r['direction'].upper()=='BUY' else r['amount']), axis=1).sum()
    est = mrow['initial_capital'] + delta
    print(f"  [{mrow['account_id']}] 初始{mrow['initial_capital']:.0f}+流水{delta:+,.0f}=现金{est:,.0f} vs DB记录{mrow['cash']:,.0f} 差{mrow['cash']-est:+,.0f}")

print("\n=== T8 成交票信号分追溯 ===")
sig = con.execute("""
SELECT REPLACE(REPLACE(stock_code,'.SZ',''),'.SH','') code, REPLACE(date,'-','') d,
 fusion_score, fusion_score_cmmr, cmmr_score
FROM 'signals.db'.signal_history WHERE REPLACE(date,'-','')>='20260801'""").df()
sig.columns=[c if '"' not in c else c.strip('"') for c in sig.columns]
for sname, sc in tl.merge(sig, left_on=['code','dn'], right_on=['code','d'], how='inner').groupby(tl['strategy'].fillna('(NULL)')):
    pass
mm = tl.merge(sig, left_on=['code','dn'], right_on=['code','d'], how='left')
mm = mm[mm['strategy'].notna()]
buys = mm[mm['direction'].str.upper()=='BUY']
sells = mm[mm['direction'].str.upper()=='SELL']
# 策略账户买入时自家信号分
print("策略账户BUY当日 fusion_score_cmmr 分布(应高):")
for s_,g in buys.groupby('strategy'):
    if len(g): print(f"  {s_}: n={len(g)} 中位cmmrp={g['fusion_score_cmmr'].median():.1f} <50占比{(g['fusion_score_cmmr']<50).mean()*100:.0f}%")
print("SELL当日分数(低分卖=正常止损/高分卖=异常):")
for s_,g in sells.groupby('strategy'):
    if len(g):
        hi = g[g['fusion_score_cmmr']>=80]
        print(f"  {s_}: n={len(g)} 中位={g['fusion_score_cmmr'].median():.1f} 高分卖(≥80){len(hi)}笔")
print("\n(只读审查完成，未写任何库)")