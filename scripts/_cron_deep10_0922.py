#!/usr/bin/env python3
import sqlite3, os, duckdb
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
tdb = duckdb.connect('tushare.db', read_only=True)
accs = ('fusion_center','center_dual','cmmr','cmmr_fusion','agent_auto','reg10_solo')
pos = led.execute("SELECT account_id,code,name,shares,avg_cost,stop_loss,target,buy_date FROM strategy_positions WHERE account_id IN (%s)" % ','.join("'"+a+"'" for a in accs)).fetchall()
def suf(c): return c+'.SH' if c.startswith(('6','9')) else c+'.SZ'
codes = sorted({suf(r[1]) for r in pos})
ph = ','.join("'"+c+"'" for c in codes)
px = {tc: (cl, pc) for tc, cl, pc in tdb.execute(f"SELECT ts_code,close,pct_chg FROM daily WHERE ts_code IN ({ph}) AND trade_date='20260922'").fetchall()}
import collections
by = collections.defaultdict(list)
for acc,c,nm,sh,cost,sl,tgt,bd in pos: by[acc].append((nm,c,cost,sl,tgt,sh,bd))
for acc, lst in by.items():
    print('--', acc)
    for nm,c,cost,sl,tgt,sh,bd in sorted(lst, key=lambda x: (px.get(suf(x[1]),(9e9,))[0])/(x[2] or 1)):
        cl, pc = px.get(suf(c), (None, None))
        dsl = f"距止损{(cl/sl-1)*100:+.1f}%" if cl and sl else '无止损'
        dtg = f"距止盈{(tgt/cl-1)*100:+.1f}%" if cl and tgt else '无止盈'
        r7 = '⚠️R7' if cl and cost and cl<=cost*0.94 else ''
        print(f"   {nm} {c} pos={((cl/cost)-1)*100 if cl else 0:+.1f}% {dsl} {dtg} {r7}")
# reg10_solo 建仓日
print('== reg10_solo buy dates ==')
print(led.execute("SELECT code,name,buy_date,avg_cost FROM strategy_positions WHERE account_id='reg10_solo' ORDER BY buy_date").fetchall())
