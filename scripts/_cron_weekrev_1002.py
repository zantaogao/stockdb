import duckdb, sqlite3
LED='/Users/zantao/.hermes/stockdb/ledger.db'
TS='/Users/zantao/.hermes/stockdb/tushare.db'
tl = sqlite3.connect(LED)
# trade_cal check
print("trade_cal 0925-1008:", tl.execute("SELECT cal_date,is_open FROM trade_cal WHERE cal_date BETWEEN '20260925' AND '20261008' ORDER BY cal_date").fetchall())

con = duckdb.connect(TS, read_only=True)

def dbmt(code):
    return code+'.SH' if code[0]=='6' else code+'.SZ'

# 1) NAV baselines: first day of each account
for s in ('agent_auto','center_dual'):
    r = tl.execute("SELECT MIN(date),nav FROM strategy_accounts WHERE account_id=? GROUP BY date ORDER BY date LIMIT 1",(s,)).fetchone()
    last = tl.execute("SELECT date,nav FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1",(s,)).fetchone()
    print(s,"first:",r,"last:",last)
# window from last review date 0924 NAV
for s in ('agent_auto','center_dual'):
    a = tl.execute("SELECT nav FROM strategy_accounts WHERE account_id=? AND date='20260924'",(s,)).fetchone()
    b = tl.execute("SELECT nav FROM strategy_accounts WHERE account_id=? AND date='20260930'",(s,)).fetchone()
    print(s,"0924->0930:",round((b[0]/a[0]-1)*100,2),"%")

# 2) index 000852.SH (中证1000) 0924 close -> 0930 close
for tbl in ('index_daily',):
    try:
        rows = con.execute(f"SELECT trade_date,close FROM {tbl} WHERE ts_code='000852.SH' AND trade_date BETWEEN '20260924' AND '20260930' ORDER BY trade_date").fetchall()
        print("000852:",rows)
    except Exception as e:
        print("idx err",e)

# 3) sold this week: close on sell date, close 0930, max close after sell
sold = [('300500','启迪设计',9.53),('301053','远信工业',33.94),('300881','盛德鑫泰',29.83),
        ('688592','司南导航',22.33),('688659','元琛科技',9.09),('603409','汇通控股',17.53),
        ('300982','苏文电能',14.26),('301276','嘉曼服饰',17.26),('300970','华绿生物',16.92),
        ('603382','海阳科技',18.88)]
print("--- sold: sell_px | close on sell day | last 0930 close | max close after sell")
for code,name,spx in sold:
    rows = con.execute("SELECT trade_date,close FROM daily WHERE ts_code=? AND trade_date>='20260928' AND trade_date<='20260930' ORDER BY trade_date",(dbmt(code),)).fetchall()
    print(code,name,"sell",spx,rows)

# 4) holdings current pnl at 0930 close
held = [('001238','浙江正特',23.68,3000),('002253','川大智胜',8.87,16600),('002554','惠博普',2.74,100),
        ('003027','同兴科技',16.66,100),('300381','溢多利',5.74,25800),('300640','德艺文创',6.22,23000),
        ('300837','浙矿股份',21.71,3000),('301167','建研设计',13.27,6300),('688096','京源环保',7.28,20000)]
print("--- held: cost | 0930 close | pnl% | float pnl yuan")
tot=0
for code,name,cost,sh in held:
    r = con.execute("SELECT close FROM daily WHERE ts_code=? AND trade_date='20260930'",(dbmt(code),)).fetchone()
    if r:
        p=(r[0]/cost-1)*100; y=(r[0]-cost)*sh; tot+=y
        print(code,name,cost,r[0],round(p,2),round(y))
print("total float pnl:",round(tot))
