import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))

c = sqlite3.connect('signals.db')
cols = [r[1] for r in c.execute('pragma table_info(mean_reversion_signals)')]
print('mr signal cols:', cols)
dcol = 'date' if 'date' in cols else cols[1]
print('mr signal count/max:', c.execute(f'select count(*), max({dcol}) from mean_reversion_signals').fetchone())
print('last 5:')
for r in c.execute(f'select * from mean_reversion_signals order by {dcol} desc limit 5'):
    print(' ', r)

L = sqlite3.connect('ledger.db')
print('\nmeta cols:', [r[1] for r in L.execute('pragma table_info(strategy_accounts_meta)')])
for r in L.execute('select * from strategy_accounts_meta'):
    print(' meta:', r)
print('\npos cols:', [r[1] for r in L.execute('pragma table_info(strategy_positions)')])
for r in L.execute("select * from strategy_positions"):
    print(' pos:', r)
print('\ntrade_log cols:', [r[1] for r in L.execute('pragma table_info(trade_log)')])
rows = L.execute("select * from trade_log order by rowid desc limit 10").fetchall()
for r in rows:
    print(' trade:', r)
