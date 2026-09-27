import json, sqlite3
import duckdb

d = json.load(open('sim_accounts/agent_auto.json'))
pos = d['positions']
codes = [p['code'] for p in pos]

# minute parquet per code
import pandas as pd
pref = {'6':'sh','0':'sz','3':'sz'}
print('--- unrealized from 5min last close (09-24) ---')
tot_cost = tot_val = 0
rows = []
for p in pos:
    c = p['code']
    f = f"minutes/5min/{pref[c[0]]}_{c}.parquet"
    try:
        df = pd.read_parquet(f)
        last = df[df['date']=='2026-09-24']
        px = float(last['close'].iloc[-1])
    except Exception as e:
        px = p['avg_cost']
        print(f'{c} fallback {e}')
    s = p['shares']; cst = p['avg_cost']
    cost = cst*s; val = px*s
    tot_cost += cost; tot_val += val
    rows.append((c, p['name'], s, cst, px, (px/cst-1)*100, val-cost))
for r in sorted(rows, key=lambda x: -x[5]):
    print(f"{r[0]} {r[1]}: qty={r[2]} cost={r[3]} close24={r[4]} pnl={r[5]:+.2f}% val_pnl={r[6]:+.0f}")
print(f"TOTAL cost={tot_cost:.0f} val={tot_val:.0f} unreal={tot_val-tot_cost:+.0f} ({(tot_val/tot_cost-1)*100:+.2f}%)")
print(f"nav check: val+cash={tot_val+d['cash']:.0f} vs nav_history 1002387")

# center_dual week
cd = duckdb.connect('ledger.db', read_only=True) if False else None
con = sqlite3.connect('ledger.db')
cd_rows = con.execute("SELECT date,nav FROM strategy_accounts WHERE account_id='center_dual' AND date>='2026-09-18' ORDER BY date").fetchall()
print('center_dual:', cd_rows)
ag = con.execute("SELECT date,nav,market_ret FROM strategy_accounts WHERE account_id='agent_auto' AND date>='2026-09-18' ORDER BY date").fetchall()
print('agent_auto mkt:', ag)
mkt = 1.0
for r in ag[1:]:
    mkt *= (1 + r[2]/100)
print(f"CSI1000 cum this week (09-18close->09-24): {(mkt-1)*100:+.2f}%")

# sells pnl this week
sells = con.execute("SELECT code,name,notes FROM trade_log WHERE strategy='agent_auto' AND direction='SELL' AND trade_date>='2026-09-19'").fetchall()
tot = 0
for c,n,notes in sells:
    p = float(notes.split('pnl ')[1].rstrip('%'))
    amt = con.execute("SELECT amount FROM trade_log WHERE strategy='agent_auto' AND direction='SELL' AND code=? AND trade_date>='2026-09-19'", (c,)).fetchone()[0]
    yuan = amt*p/100/(1+p/100) if p else 0
    tot += yuan
    print(f'SELL {c} {n}: pnl={p}% ~{yuan:+.0f}元')
print(f'week realized total ~{tot:+.0f}元')
buys = con.execute("SELECT code,name,amount FROM trade_log WHERE strategy='agent_auto' AND direction='BUY' AND trade_date>='2026-09-19'").fetchall()
print('BUY:', buys, 'sum=', sum(b[2] for b in buys))
