import sqlite3, os, json, datetime
base = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(base, 'ledger.db'))
c.row_factory = sqlite3.Row

def cols(t):
    try:
        return [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
    except Exception as e:
        return ['ERR', str(e)]

for t in ['trade_log','strategy_accounts_meta','strategy_positions','trade_cooldown','trade_tp_ban','ca_adjustments','execution_logs']:
    print(t, '->', cols(t))

print('==== strategy_accounts_meta (all cols) ====')
for r in c.execute("SELECT * FROM strategy_accounts_meta"):
    print(dict(r))
print('==== strategy_positions summary ====')
for r in c.execute("SELECT account_id, COUNT(*), MAX(buy_date) FROM strategy_positions GROUP BY account_id"):
    print(tuple(r))
print('==== cooldown ====')
for r in c.execute("SELECT * FROM trade_cooldown WHERE REPLACE(date,'-','')>='20260910'"):
    print(dict(r))
print('==== tp_ban recent ====')
for r in c.execute("SELECT * FROM trade_tp_ban ORDER BY rowid DESC LIMIT 10"):
    print(dict(r))
print('==== ca_adjustments recent ====')
for r in c.execute("SELECT * FROM ca_adjustments ORDER BY rowid DESC LIMIT 8"):
    print(dict(r))
print('==== ca_run_log ====')
for r in c.execute("SELECT * FROM ca_run_log ORDER BY rowid DESC LIMIT 8"):
    print(dict(r))
