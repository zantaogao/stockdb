import sqlite3, json, glob, os
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
try:
    n = con.execute("SELECT COUNT(*), MAX(date) FROM strategy_positions WHERE account_id='agent_auto'").fetchall()
    print('ledger agent_auto positions:', n)
except Exception as e:
    print(e)
for f in sorted(glob.glob(os.path.expanduser('~/.hermes/stockdb/sim_accounts/*.json'))):
    try:
        d = json.load(open(f))
        if isinstance(d, dict):
            print(os.path.basename(f), 'positions=', len(d.get('positions', [])), 'cash=', d.get('cash'), 'nav=', d.get('nav'))
        else:
            print(os.path.basename(f), 'list len', len(d))
    except Exception as e:
        print(os.path.basename(f), 'ERR', e)
