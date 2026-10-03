import sqlite3, re, duckdb
tl = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print("中证1000:", con.execute("SELECT date,close FROM index_daily WHERE index_code='000852' AND CAST(date AS VARCHAR)>='20260924' ORDER BY date LIMIT 10").fetchall())
rows = tl.execute("SELECT trade_date,code,name,amount,notes FROM trade_log WHERE strategy='agent_auto' AND direction='SELL' ORDER BY trade_date DESC LIMIT 12").fetchall()
tot=0
for d,c,n,amt,notes in rows:
    m=re.search(r'pnl (-?[\d.]+)%',notes or '')
    if m:
        p=float(m.group(1)); realized=amt*p/(100+p); tot+=realized
        print(d,c,n,"proceeds",amt,"pnl%",p,"realized≈",round(realized))
    else:
        print(d,c,n,"NO PNL MARK",notes)
print("realistic realized (last 12 sells) ≈",round(tot))
