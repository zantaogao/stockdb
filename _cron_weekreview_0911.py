import sqlite3, json
from collections import defaultdict

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
rows = c.execute("SELECT trade_date,code,name,direction,amount,quantity FROM trade_log WHERE strategy='agent_auto' ORDER BY trade_date, rowid").fetchall()

cost = defaultdict(lambda: [0.0, 0.0])  # qty, costamt
week_real = 0.0
week_sells = 0
week_wins = 0
per_sell = []
for d, code, name, dr, amt, qty in rows:
    if dr == 'BUY':
        cost[code][0] += qty
        cost[code][1] += amt
    else:
        if cost[code][0] > 0:
            avg = cost[code][1] / cost[code][0]
            q = min(qty, cost[code][0])
            pnl = (amt / qty - avg) * q
            cost[code][0] -= q
            cost[code][1] -= avg * q
            if d >= '2026-09-05':
                week_real += pnl
                week_sells += 1
                if pnl > 0:
                    week_wins += 1
                per_sell.append((d, code, name, round(pnl, 1), round(pnl / (avg * q) * 100, 2)))

print("week realized pnl:", round(week_real, 1), "| sells:", week_sells, "| wins:", week_wins)
for s in per_sell:
    print(s)

print("\nholdings now:")
try:
    for r in c.execute("SELECT * FROM holdings WHERE strategy='agent_auto'").fetchall():
        print(r)
except Exception as e:
    print("holdings err:", e)
print("\ncash:", c.execute("SELECT * FROM account_balance WHERE strategy='agent_auto'").fetchall())

# buy->sell trajectory: for each of this week's buys, price path via daily
import duckdb
d = duckdb.connect('/Users/zantao/.hermes/tushare.db' , read_only=True) if False else duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
buys = [r for r in rows if r[0] >= '2026-09-05' and r[3] == 'BUY']
print("\nbuy price path (buy px -> daily closes after):")
for d_, code, name, dr, amt, qty in buys:
    ts = code + ('.SZ' if code[0] in '03' else ('.SH' if code[0] in '68' else '.SZ'))
    ds = d_.replace('-', '')
    px = d.execute("SELECT trade_date, close FROM daily WHERE ts_code=? AND trade_date>=? ORDER BY trade_date", [ts, ds]).fetchall()
    print(code, name, d_, [(x[0][4:], x[1]) for x in px[:6]])
