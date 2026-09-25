#!/usr/bin/env python3
"""第三轮收尾：main+NULL合并回放、300109等异常票逐笔、NULL策略27条来源定位"""
import sqlite3, pandas as pd, numpy as np

led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
pd.set_option('display.width', 240); pd.set_option('display.max_rows', 300)
tl = pd.read_sql("SELECT rowid rid, * FROM trade_log", led)
tl['dn']=tl['trade_date'].str.replace('-','',regex=False)
hold = pd.read_sql("SELECT * FROM holdings", led)
spos = pd.read_sql("SELECT * FROM strategy_positions", led)

print("=== main+NULL 合并回放 vs holdings ===")
m = tl[tl['strategy'].isin(['main'])|tl['strategy'].isna()].assign(t2=lambda x:x['trade_time'].astype(str)).sort_values(['dn','t2','rid'])
pos={}
for _,r in m.iterrows():
    pos[r['code']]=pos.get(r['code'],0)+(r['quantity'] if r['direction'].upper()=='BUY' else -r['quantity'])
hmap=dict(zip(hold['code'],hold['shares']))
diff=[]
for c in sorted(set(pos)|set(hmap)):
    p_,h_=pos.get(c,0),hmap.get(c,0)
    if p_!=h_: diff.append((c,p_,h_,p_-h_))
print(f"差异{len(diff)}只 (回放, holdings, 差):")
for x in diff: print("  ",x)
neg=[c for c,p_,h_,d_ in diff if p_<0]
print("回放出现负持仓(卖超):", neg)

print("\n=== 异常票逐笔 ===")
for c,acc in [('300109','fusion3f'),('600855','center_dual'),('300157','center_dual'),('300986','center_dual'),('300368','fusion3f'),('688575','fusion3f'),('300278','fusion_center')]:
    g=tl[(tl['code']==c)&(tl['strategy']==acc)].sort_values('rid')
    name = hold[hold.code==c]['name'].iloc[0] if (hold.code==c).any() else (spos[(spos.code==c)&(spos.account_id==acc)]['name'].iloc[0] if len(spos[(spos.code==c)&(spos.account_id==acc)]) else '?')
    db_sh = hmap.get(c) if acc in('main','(NULL)') else (spos[(spos.code==c)&(spos.account_id==acc)]['shares'].sum() if len(spos[(spos.code==c)&(spos.account_id==acc)]) else 0)
    print(f"  [{acc}] {c} {name} DB持仓={db_sh}")
    print(g[['rid','dn','direction','price','quantity','strategy']].to_string(index=False).replace('\n','\n    '))

print("\n=== NULL策略27条SELL的id分布（判断写入时间）===")
nul=tl[tl['strategy'].isna()]
print("id范围:", nul['rid'].min(), "-", nul['rid'].max())
print("相邻有策略记录的id:", tl[(tl['rid'].between(nul['rid'].min()-3,nul['rid'].min())) & (tl['strategy'].notna())][['rid','dn','code','direction','strategy']].to_string(index=False))
print("id上限之后首条:", tl[(tl['rid']>nul['rid'].max()) & (tl['strategy'].notna())][['rid','dn','code','direction','strategy']].head(3).to_string(index=False))
print("\n=== NULL记录价 vs 当日真实区间（防编价）===")
import duckdb
con=duckdb.connect('tushare.db',read_only=True)
mk=con.execute(f"""SELECT REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') c, trade_date d, high, low FROM daily
WHERE trade_date BETWEEN '20260818' AND '20260825' AND REPLACE(REPLACE(ts_code,'.SZ',''),'.SH','') IN ({','.join("'"+c+"'" for c in nul['code'].unique())})""").df()
j=nul.merge(mk,left_on=['code','dn'],right_on=['c','d'])
out=j[(j['price']>j['high']*1.001)|(j['price']<j['low']*0.999)]
print("27条越界:",len(out))
print("\n=== 8/31 科创/创业板买100股（违反200股申报且违反MIN_QTY修复后规则?）===")
b31=tl[(tl['dn']=='20260831')&(tl['direction']=='BUY')&(tl['code'].str.startswith(('300','301','688')))]
print(b31[['rid','code','price','quantity','strategy','trade_time']].to_string(index=False))