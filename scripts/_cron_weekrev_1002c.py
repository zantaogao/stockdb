import sqlite3, re
print("中证1000 idx:", [r for r in __import__('duckdb').connect('/Users/zantao/.hermes/stockdb/tushare.db',read_only=True).execute("SELECT DISTINCT index_code FROM index_daily LIMIT 20").fetchall()])
tl = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')

rows = tl.execute("SELECT trade_date,code,name,amount,notes FROM trade_log WHERE strategy='agent_auto' AND direction='SELL' AND trade_date>='20260928' ORDER BY trade_date").fetchall()
tot=0
for d,c,n,amt,notes in rows:
    m=re.search(r'pnl (-?[\d.]+)%',notes or '')
    if m:
        p=float(m.group(1)); realized=amt*p/(100+p); tot+=realized
        print(d,c,n,"proceeds",amt,"pnl%",p,"realized≈",round(realized))
print("realized total ≈",round(tot))
# defense state
try:
    print("defense_state:", tl.execute("SELECT * FROM defense_state").fetchall()[:10])
except Exception as e: print("def err",e)
