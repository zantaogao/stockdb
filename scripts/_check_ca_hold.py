# 300818在哪个策略账户？ledger.strategy_positions
import json, glob, sqlite3
led = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
print('ledger tables:', [r[0] for r in led.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
for t in ('strategy_positions','strategy_accounts'):
    try:
        cols=[r[1] for r in led.execute(f"PRAGMA table_info({t})").fetchall()]
        print(t, cols)
        print(led.execute(f"SELECT * FROM {t} WHERE {('code' if t=='strategy_positions' else '1=1')} LIKE '%300818%' OR 1=1").fetchall()[:30])
    except Exception as e:
        print(t, 'ERR', e)