import sqlite3, os, sys
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
sys.path.insert(0, '.')

for db in ['signals.db', 'ledger.db']:
    c = sqlite3.connect(db)
    r = c.execute("SELECT name FROM sqlite_master WHERE name LIKE '%stock_basic%'").fetchall()
    print(db, 'stock_basic tables:', r)
    if r:
        t = r[0][0]
        cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})")]
        print('  cols:', cols[:12])
        print('  rows:', c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
        print('  sample:', c.execute(f"SELECT * FROM {t} LIMIT 2").fetchall())
    c.close()

# Replicate get_industry exactly as intraday_decision does
from core.db import get_state_db
conn = get_state_db()
for code in ['688257', '688186', '301125']:
    try:
        row = conn.execute(f"SELECT industry FROM sig.stock_basic WHERE stock_code='{code}'").fetchone()
        print(code, 'get_industry query ->', repr(row))
    except Exception as e:
        print(code, 'get_industry query EXC:', e)
conn.close()