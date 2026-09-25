#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五榜技术形态 + 持仓风控距离（只读）"""
import duckdb, sqlite3, os
DB='/Users/zantao/.hermes/stockdb'
td=duckdb.connect(os.path.join(DB,'tushare.db'), read_only=True)

lists = {
 '三模型融合': ['300952','300680','300658','603966','001332','301479','301093','688191','301237','301413'],
 'CMMR独立': ['603801','301130','688793','300381','002674','300254','000710','000931','603823','301190'],
 'CMMR+融合': ['688217','002535','688606','301130','300886','688793','603382','300898','688681','000014'],
 '中枢版': ['600880','000923','603079','603103','603331','301113','000032','300291','000990','300299'],
 '中枢版+三模型': ['002866','000990','603863','688273','605286','600137','300100','688638','603079','001256'],
}
def suf(c): return c+('.SH' if c[0]=='6' else '.SZ')

def tech(codes):
    out={}
    for c in codes:
        ts=suf(c)
        try:
            rows=td.execute("SELECT close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 21",[ts]).fetchall()
            if len(rows)<21: out[c]=None; continue
            closes=[r[0] for r in rows]  # desc
            last=closes[0]
            ma20=sum(closes[:20])/20
            var=(sum((x-ma20)**2 for x in closes[:20])/20)**0.5
            ub,lb=ma20+2*var,ma20-2*var
            bbpos=(last-lb)/(ub-lb)*100 if ub>lb else 50
            ret5=(last/closes[5]-1)*100
            # 20日前高（不含今日）
            hi20=max(td.execute("SELECT high FROM daily WHERE ts_code=? AND trade_date<? ORDER BY trade_date DESC LIMIT 20",[ts, '20260907']).fetchall().__iter__().__next__()[0] for _ in [0]) if False else None
            his=td.execute("SELECT MAX(high) FROM daily WHERE ts_code=? AND trade_date<'20260907' AND trade_date>=(SELECT MIN(trade_date) FROM (SELECT trade_date FROM daily WHERE ts_code<? ORDER BY trade_date DESC LIMIT 20))",[ts,ts]).fetchone()[0]
            newhigh20 = last>=his if his else None
            out[c]=dict(close=round(last,2), ma20dev=round((last/ma20-1)*100,1), bbpos=round(bbpos,0), ret5=round(ret5,1), new20high=newhigh20)
        except Exception as e:
            out[c]='ERR '+str(e)[:60]
    return out

for name,codes in lists.items():
    print('=====',name)
    t=tech(list(dict.fromkeys(codes)))
    for c in codes:
        print(c, t.get(c))

print('===== 主账户风控距离 =====')
led=sqlite3.connect(os.path.join(DB,'ledger.db'))
holds=led.execute("SELECT code,name,avg_cost,shares,target_price,stop_loss FROM holdings WHERE status='hold'").fetchall()
for code,name,cost,sh,tgt,sl in holds:
    ts=suf(code)
    row=td.execute("SELECT close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",[ts]).fetchone()
    if not row: print(code,name,'NOCLOSE'); continue
    px=row[0]
    dsl=(px/sl-1)*100 if sl else None
    dtg=(tgt/px-1)*100 if tgt and px else None
    print(f"{code} {name} close={px:.2f} cost={cost} 盈亏={(px/cost-1)*100:+.1f}% 距止损={dsl:+.1f}% 距目标={dtg:+.1f}%")

print('===== 策略账户R7浮亏(现价<=成本*0.94) =====')
rows=led.execute("SELECT account_id,ts_code,shares,avg_cost FROM strategy_positions").fetchall()
for acc,ts,sh,cost in rows:
    r=td.execute("SELECT close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",[ts]).fetchone()
    if r and cost and r[0]<=cost*0.94:
        print(acc,ts,f"close={r[0]} cost={cost} {(r[0]/cost-1)*100:+.1f}%")
print('done')