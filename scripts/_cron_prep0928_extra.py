# 盘前0928 补查：主账户0924流水 / 卖出敞口折算 / 0925休市核实 / USD兑日元
import sqlite3, duckdb, requests

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
print('== 主账户(strategy=main或空) 0924 流水 ==')
for r in c.execute("SELECT code,name,direction,price,quantity,amount,strategy,trade_time,notes FROM trade_log WHERE trade_date>='2026-09-24' AND (strategy LIKE '%main%' OR strategy IS NULL OR notes LIKE '%主账户%') ORDER BY trade_time").fetchall():
    print(r)
print('== 全部strategy取值 ==')
print(c.execute("SELECT DISTINCT strategy FROM trade_log WHERE trade_date>='2026-09-20'").fetchall())

print('== 主账户持仓市值折算（0925/0927估值价） ==')
rows = c.execute("SELECT code,name,avg_cost,shares,latest_price,stop_loss,target_price FROM holdings WHERE status='hold'").fetchall()
tot = 161.25
risk = []
for code,name,cost,sh,px,sl,tp in rows:
    mv = sh*px; tot += mv
    dist_sl = (px/sl-1)*100 if sl else None
    print(f"{code} {name} mv {mv:,.0f} pnl {(px/cost-1)*100:+.1f}% distSL {dist_sl if dist_sl is None else round(dist_sl,1)}")
print('total assets approx:', tot)
kangxin = dict((r[0], r[3]*r[4]) for r in rows).get('600076',0)
print('康欣新材 mv % of total:', kangxin/tot*100)

print('== trade_cal 0925-0928 ==')
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
try:
    print(db.execute("SELECT cal_date,is_open FROM trade_cal WHERE cal_date BETWEEN '20260924' AND '20260929'").fetchall())
except Exception as e:
    print('no trade_cal', e)

print('== USD/JPY ==')
r = requests.get('https://hq.sinajs.cn/list=fx_susdjpy,fx_shusdcny', headers={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'}, timeout=10)
r.encoding='gbk'
print(r.text)
