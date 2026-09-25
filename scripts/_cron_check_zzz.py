import sqlite3, collections, os
base = os.path.expanduser('~/.hermes/stockdb')
# What is industry 'ZZZ' in holdings, and where does intraday_decision get industry from?
c = sqlite3.connect(f'file:{base}/ledger.db?mode=ro', uri=True)
try:
    rows = c.execute("SELECT industry, COUNT(*) FROM holdings GROUP BY industry ORDER BY 2 DESC").fetchall()
    print('holdings industries:', rows[:15])
except Exception as e:
    print('holdings query err:', e)
    cols = [r[1] for r in c.execute("PRAGMA table_info(holdings)")]
    print('holdings cols:', cols)