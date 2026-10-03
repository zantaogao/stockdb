import sqlite3
led = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
print('--- holdings 605598 ---')
print([x[1] for x in led.execute("PRAGMA table_info(holdings)")])
for r in led.execute("SELECT rowid,code,name,status,buy_date,avg_cost,shares,latest_price,pnl,pnl_pct,target_price,stop_loss,update_time FROM holdings WHERE code LIKE '%605598%'").fetchall():
    print(r)
print('--- 持仓表有哪些账户维度? strategy_accounts ---')
try:
    print([x[1] for x in led.execute("PRAGMA table_info(strategy_accounts)")])
    for r in led.execute("SELECT * FROM strategy_accounts").fetchall(): print(r)
except Exception as e: print(e)
print('--- trade_log 605598 ---')
for r in led.execute("SELECT trade_date,trade_time,direction,price,quantity,amount,strategy,signal_score,notes FROM trade_log WHERE code LIKE '%605598%' ORDER BY trade_date,trade_time").fetchall():
    print(r)
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('--- signal_history ---')
print(sig.execute("SELECT date,fusion_score,final_score,cmmr_score,reg10,reg40 FROM signal_history WHERE stock_code LIKE '%605598%' ORDER BY date DESC LIMIT 3").fetchall())
print('--- fusion_3f ---')
print(sig.execute("SELECT date,fusion_3f_score,signal FROM fusion_3f_signals WHERE stock_code LIKE '%605598%' ORDER BY date DESC LIMIT 3").fetchall())
