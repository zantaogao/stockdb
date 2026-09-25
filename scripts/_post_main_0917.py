#!/usr/bin/env python3
# 主账户持仓日线形态 + 近期卖出（冷却期）（只读）
import duckdb, sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
TU = duckdb.connect('tushare.db', read_only=True)
LG = sqlite3.connect('file:ledger.db?mode=ro', uri=True)

main = ['301237.SZ','688093.SH','301283.SZ','002454.SZ','688191.SH','600076.SH','603966.SH',
        '601615.SH','688186.SH','301093.SZ','300658.SZ','603202.SH','001332.SZ','301590.SZ',
        '301110.SZ','605598.SH']
for c in main:
    rows = TU.execute("SELECT trade_date,close,pct_chg,vol,high,low FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 30", [c]).fetchall()
    if not rows:
        print(c,'NOROW'); continue
    rows = list(reversed(rows))
    closes=[r[1] for r in rows]
    ma10=sum(closes[-10:])/10; ma20=sum(closes[-20:])/20
    var=sum((x-ma20)**2 for x in closes[-20:])/20; sd=var**0.5
    up=ma20+2*sd; dn=ma20-2*sd; last=closes[-1]
    hi30=max(r[4] for r in rows); lo30=min(r[5] for r in rows)
    vol5=sum(r[3] for r in rows[-6:-1])/5
    # 连续涨跌
    streak=0
    for r in reversed(rows):
        if (r[2]>0)!=(streak>0) and streak!=0: break
        streak = streak+1 if r[2]>0 else (streak-1 if r[2]<0 else streak)
    chg5=(closes[-1]/closes[-6]-1)*100
    print(c, 'last=%.2f d1=%+.2f chg5=%+.1f%% boll=%.0f%% ma10dev=%+.1f%% d30hi=%+.1f%% d30lo=%+.1f%% volratio=%.2f streak=%d' % (
        last, rows[-1][2], chg5, (last-dn)/(up-dn)*100 if up>dn else 50,
        (last/ma10-1)*100, (last/hi30-1)*100, (last/lo30-1)*100,
        rows[-1][3]/vol5 if vol5 else 0, streak))

print('===== trade_log last 10 days =====')
for r in LG.execute("SELECT trade_date, stock_code, direction, price, volume, strategy FROM trade_log WHERE trade_date>='2026-09-07' ORDER BY trade_date").fetchall():
    print(r)
