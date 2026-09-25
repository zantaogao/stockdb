import sqlite3, os
os.chdir('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('signals.db')
print('=== tdx_intraday_feat cols ===')
print([r[1] for r in c.execute("PRAGMA table_info(tdx_intraday_feat)")])
print('=== latest dates ===')
try:
    print(c.execute("SELECT MAX(dt) FROM tdx_intraday_feat").fetchall())
except Exception as e:
    print('dt err', e)
