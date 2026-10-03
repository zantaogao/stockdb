import sqlite3, os
os.chdir('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('ledger.db')
print("trade_log cols stop?", [r[1] for r in c.execute("PRAGMA table_info(holdings)").fetchall()])
print("\n== 今日 0930 全部成交 ==")
for r in c.execute("SELECT strategy,trade_date,code,name,direction,price,quantity FROM trade_log WHERE trade_date>='2026-09-30' ORDER BY strategy,trade_time").fetchall():
    print(r)
print("\n== 0928-0929 策略账户成交(查10d/CMMR+重建) ==")
for r in c.execute("SELECT strategy,trade_date,code,name,direction,price,quantity FROM trade_log WHERE trade_date>='2026-09-28' AND strategy!='main' ORDER BY trade_date").fetchall():
    print(r)
print("\n== holdings 主账户(含止损止盈列) ==")
for r in c.execute("SELECT * FROM holdings").fetchall():
    print(r)
c.close()
