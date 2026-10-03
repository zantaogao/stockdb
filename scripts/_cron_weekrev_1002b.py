import duckdb, sqlite3
LED='/Users/zantao/.hermes/stockdb/ledger.db'
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tl = sqlite3.connect(LED)
rows = con.execute("SELECT CAST(date AS VARCHAR),close FROM index_daily WHERE index_code='000852.SH' AND CAST(date AS VARCHAR) BETWEEN '20260922' AND '20260930' ORDER BY date").fetchall()
print("中证1000:",rows)
if len(rows)>=2:
    a=[r for r in rows if r[0].replace('-','')=='20260924'][0][1]; b=rows[-1][1]
    print("index 0924->0930:",round((b/a-1)*100,2),"%")

# sold shares & opportunity cost vs 0930 close
sold = [('300500','启迪设计',9.53,1600),('301053','远信工业',33.94,2900),('300881','盛德鑫泰',29.83,3000),
        ('688592','司南导航',22.33,4400),('688659','元琛科技',9.09,14700),('603409','汇通控股',17.53,8200),
        ('300982','苏文电能',14.26,4900),('301276','嘉曼服饰',17.26,500),('300970','华绿生物',16.92,1000),
        ('603382','海阳科技',18.88,3500)]
tot=0
print("--- sold vs holding-to-0930 (yuan diff)")
for code,name,spx,sh in sold:
    ts = code+'.SH' if code[0]=='6' else code+'.SZ'
    r = con.execute("SELECT close FROM daily WHERE ts_code=? AND trade_date='20260930'",(ts,)).fetchone()
    d=(r[0]-spx)*sh; tot+=d
    print(code,name,"sell",spx,"0930",r[0],"diff",round(d))
print("net opportunity cost of 10 sells (hold-to-0930 minus actual):",round(tot))
# realized pnl this week from notes
import re
wl=tl.execute("SELECT trade_date,code,name,direction,amount,notes FROM trade_log WHERE strategy='agent_auto' AND trade_date>='20260928' AND direction='SELL'").fetchall()
rp=0
for d,c,n,a,notes in wl:
    m=re.search(r'pnl (-?[\d.]+)%',notes or '')
    print(d,c,n,"amt",a,"pnl%",m.group(1) if m else None)
# buy prices vs 0930
buys=[('301167','建研设计',13.27,6300),('300970','华绿生物',17.18,1000),('300640','德艺文创',6.22,23000),
      ('688096','京源环保',7.28,20000),('002554','惠博普',2.74,100),('002253','川大智胜',8.87,16600),('300381','溢多利',5.74,25800)]
print("--- buys: buypx | 0930 close | unreal diff")
tb=0
for code,name,bpx,sh in buys:
    ts = code+'.SH' if code[0]=='6' else code+'.SZ'
    r = con.execute("SELECT close FROM daily WHERE ts_code=? AND trade_date='20260930'",(ts,)).fetchone()
    d=(r[0]-bpx)*sh; tb+=d
    print(code,name,bpx,r[0],round(d))
print("buys unreal total:",round(tb))
