import sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
import agent_trade_decision as A
print('STATE_DB =', A.STATE_DB)
print('exists?', A.STATE_DB.exists())
import sqlite3
c = sqlite3.connect(str(A.STATE_DB), timeout=15)
try:
    print('today agent_auto:', c.execute("SELECT trade_time, direction, code, quantity, amount FROM trade_log WHERE strategy='agent_auto' AND trade_date='2026-09-24' ORDER BY rowid").fetchall())
except Exception as e:
    print('ERR', e)
try:
    print('tables:', c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()[:10])
except Exception as e:
    print('ERR2', e)
