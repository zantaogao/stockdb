import sqlite3
from pathlib import Path

sdb = sqlite3.connect(str(Path.home() / '.hermes' / 'stockdb' / 'state.db'))
rows = sdb.execute("""
    SELECT date, stock_code, total_score FROM mean_reversion_signals
    WHERE stock_code = '__market_state__'
    ORDER BY date DESC LIMIT 5
""").fetchall()
print('market_state 记录:')
for r in rows:
    print(' ', r)
sdb.close()
