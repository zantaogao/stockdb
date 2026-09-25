#!/usr/bin/env python3
import sqlite3, os, duckdb
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
sig = sqlite3.connect('file:signals.db?mode=ro', uri=True)
tdb = duckdb.connect('tushare.db', read_only=True)

print('== 全部策略持仓(在持) R7 检查 ==')
pos = led.execute("SELECT account_id,code,name,shares,avg_cost,buy_date FROM strategy_positions").fetchall()
def suf(c): return c+'.SH' if c.startswith(('6','9')) else c+'.SZ'
codes = sorted({suf(r[1]) for r in pos})
ph = ','.join("'"+c+"'" for c in codes)
px = {tc: (cl, pc) for tc, cl, pc in tdb.execute(f"SELECT ts_code,close,pct_chg FROM daily WHERE ts_code IN ({ph}) AND trade_date='20260922'").fetchall()}
import collections
byacct = collections.defaultdict(list)
for acc, c, nm, sh, cost, bd in pos:
    cl = px.get(suf(c), (None, None))
    byacct[acc].append((nm, c, cost, cl[0], cl[1], sh, bd))
for acc, lst in byacct.items():
    tot = sum((cl or cost)*sh for nm, c, cost, cl, pc, sh, bd in lst)
    day = sum(((cl or cost) - cost)*0 + (cl or cost)*sh*((pc or 0)/100.0) for nm, c, cost, cl, pc, sh, bd in lst)
    print(f"-- {acc} n={len(lst)} 市值约={tot:,.0f} 当日涨跌贡献约={day:+,.0f}")
    for nm, c, cost, cl, pc, sh, bd in sorted(lst, key=lambda x: (x[3] or 0)/(x[2] or 1)):
        r7 = '⚠️R7破线' if cl and cost and cl <= cost*0.94 else ''
        print(f"   {nm} {c} cost={cost} close={cl} day={pc}% pos={((cl/cost)-1)*100 if cl and cost else 0:+.1f}% {r7}")

print('== 三模型 ic_daily top_ret 近6 ==')
for r in sig.execute("SELECT signal_date,ic_reg10,ic_reg20,ic_reg40,ic_fusion,top_ret,bottom_ret FROM ic_daily ORDER BY signal_date DESC LIMIT 6").fetchall():
    print(r)
print('== 昨日0921 三模型top10名单（对账Top10次日用）==')
rows = sig.execute("SELECT stock_code, fusion_score FROM signal_history WHERE date IN ('20260921','2026-09-21') AND fusion_score IS NOT NULL ORDER BY fusion_score DESC LIMIT 10").fetchall()
print(rows[:10])
