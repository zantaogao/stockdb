import sqlite3, duckdb
led=sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cols=[c[1] for c in led.execute('PRAGMA table_info(strategy_positions)')]
print('cols:',cols)
td=duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codecol='ts_code' if 'ts_code' in cols else ('code' if 'code' in cols else cols[1])
rows=led.execute(f"SELECT account_id,{codecol},avg_cost FROM strategy_positions WHERE status='hold' OR status IS NULL OR status=''").fetchall() if 'status' in cols else led.execute(f"SELECT account_id,{codecol},avg_cost FROM strategy_positions").fetchall()
worst=[]
for acc,code,cost in rows:
    s=str(code)
    ts=s if '.' in s else s+('.SH' if s[0]=='6' else '.SZ')
    r=td.execute("SELECT close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",[ts]).fetchone()
    if not r or not cost: continue
    pct=(r[0]/cost-1)*100
    worst.append((pct,acc,s,r[0],cost))
worst.sort()
for pct,acc,s,px,cost in worst[:12]:
    print(f"{acc} {s} close={px} cost={cost} {pct:+.1f}%", '<= R7破线' if pct<=-6 else '')