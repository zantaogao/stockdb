import sqlite3, os
os.chdir('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('signals.db')
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")]
print([t for t in tabs if 'tdx' in t.lower() or 'min' in t.lower() or 'idx' in t.lower() or 'index' in t.lower()])
