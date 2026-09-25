import sqlite3, duckdb, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
tdb = duckdb.connect('tushare.db', read_only=True)
closes = dict(tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date='20260910'").fetchall())
print('=== 主账户持仓 今日收盘 vs 止损/止盈 ===')
for code,name,stop,tgt in led.execute("SELECT code,name,stop_loss,target_price FROM holdings").fetchall():
    px = closes.get(code+'.SZ') or closes.get(code+'.SH')
    if px is None: px = closes.get(code)
    if px is None or not stop: print(code,name,'nopx'); continue
    ds=(px/stop-1)*100
    dt=(tgt/px-1)*100 if tgt else None
    print(code,name,'close=%.2f stop=%.2f dist_stop=%.2f%% tgt=%s dist_tgt=%s'%(px,stop,ds,tgt,('%.1f%%'%dt) if dt is not None else '-'))
print()
print('=== 策略账户 R7: 现价<=成本*0.94 ===')
for acct,code,name,shares,cost in led.execute("SELECT account_id,code,name,shares,avg_cost FROM strategy_positions").fetchall():
    px = closes.get(code+'.SZ') or closes.get(code+'.SH') or closes.get(code)
    if px and cost and px <= cost*0.94:
        print(acct, code, name, 'cost=%.2f px=%.2f 亏%.1f%%'%(cost,px,(px/cost-1)*100))
