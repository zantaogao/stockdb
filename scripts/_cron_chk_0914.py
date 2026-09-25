import sqlite3, os, json, datetime
base = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(base, 'ledger.db'))
c.row_factory = sqlite3.Row
print('== now ==', datetime.datetime.now())
print('== tables ==', [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")])

def show(sql, label):
    print('----', label)
    try:
        for r in c.execute(sql):
            print(tuple(r))
    except Exception as e:
        print('ERR', e)

show("SELECT * FROM trade_log ORDER BY trade_date DESC, rowid DESC LIMIT 25", 'trade_log last25')
# distinct accounts + latest date
try:
    show("SELECT account_id, MAX(trade_date), COUNT(*) FROM trade_log WHERE REPLACE(trade_date,'-','')>='20260901' GROUP BY account_id", 'trade_log by acct since 0901')
except Exception as e:
    print(e)
show("SELECT * FROM account_balance", 'account_balance')
try:
    show("SELECT account_id, MAX(REPLACE(date,'-','')) FROM nav_history GROUP BY account_id", 'nav max')
except Exception as e:
    print('nav_history', e)
