#!/usr/bin/env python3
# 周复盘0918 v2：持仓浮盈 + 本周平仓票卖后走势（DuckDB tushare）
import sqlite3, os, duckdb
BASE = os.path.expanduser('~/.hermes/stockdb')
led = sqlite3.connect(BASE + '/ledger.db')
tsh = duckdb.connect(BASE + '/tushare.db', read_only=True)

def last_close(code, after=None):
    q = "SELECT date, close FROM stock_daily WHERE stock_code=? "
    a = [code]
    if after:
        q += "AND date>? "
        a.append(after)
    q += "ORDER BY date"
    return tsh.execute(q, a).fetchall()

pos = led.execute("SELECT code,name,shares,avg_cost,buy_date,peak_price FROM strategy_positions WHERE account_id='agent_auto'").fetchall()
print('=== 持仓浮盈（最新收盘） ===')
tot_mv = tot_cost = 0.0
for code, name, sh, cost, bd, peak in pos:
    rows = last_close(code)
    if not rows:
        print(f'{code} {name}: 无行情'); continue
    d, close = rows[-1]
    mv = sh * close; cst = sh * cost
    tot_mv += mv; tot_cost += cst
    print(f'{code} {name} 买{bd} 成本{cost:.2f} 收{close}({d}) 浮动{100*(close/cost-1):+.2f}% 市值{mv:,.0f} 峰值记{peak}')
print(f'合计 市值{tot_mv:,.0f} 成本{tot_cost:,.0f} 浮盈{tot_mv-tot_cost:+,.0f} ({100*(tot_mv/tot_cost-1):+.2f}%)')

print()
print('=== 本周平仓票：卖出后走势 ===')
sells = led.execute("SELECT trade_date,code,name,price,notes FROM trade_log WHERE strategy='agent_auto' AND direction='SELL' AND trade_date>='2026-09-14' ORDER BY trade_date").fetchall()
for d, code, name, sp, notes in sells:
    rows = last_close(code, after=d)
    if not rows:
        print(f'{d}卖 {code} {name} @{sp}: 卖后无行情'); continue
    lo = min(r[1] for r in rows); hi = max(r[1] for r in rows); last = rows[-1]
    print(f'{d}卖 {code} {name} @{sp} -> 最新{last[1]}({last[0]}) {100*(float(last[1])/sp-1):+.2f}% | 卖后最低{100*(float(lo)/sp-1):+.2f}% 最高{100*(float(hi)/sp-1):+.2f}%')

print()
print('=== 本周买入且仍在持仓 ===')
held = {p[0] for p in pos}
buys = led.execute("SELECT trade_date,code,name,price FROM trade_log WHERE strategy='agent_auto' AND direction='BUY' AND trade_date>='2026-09-14' ORDER BY trade_date").fetchall()
for d, code, name, bp in buys:
    if code not in held: continue
    rows = last_close(code)
    if rows:
        print(f'{d}买 {code} {name} @{bp} -> 最新{rows[-1][1]}({rows[-1][0]}) {100*(float(rows[-1][1])/bp-1):+.2f}%')

print()
print('=== 中证1000 逐日（本周） ===')
for d, cl in tsh.execute("SELECT date, close FROM index_daily WHERE index_code='000852.SH' AND date>='2026-09-11' ORDER BY date").fetchall():
    print(d, cl)
