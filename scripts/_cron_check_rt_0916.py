import sys, time
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import fetch_prices_batch
import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
pos = [r[0] for r in c.execute("SELECT DISTINCT substr(code,1,6) FROM strategy_positions WHERE account_id='fusion_center'")]
print('positions:', pos)
for attempt in range(2):
    rtp = fetch_prices_batch(pos)
    print('attempt', attempt, 'got', len(rtp), dict(list(rtp.items())[:5]))
    time.sleep(2)
