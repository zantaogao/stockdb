import duckdb, sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{BASE}/tushare.db', read_only=True)
print("board_daily cols:", [r[1] for r in t.execute("PRAGMA table_info(board_daily)").fetchall()])
print(t.execute("SELECT * FROM board_daily LIMIT 5").fetchall())
print("board_daily max date:", t.execute("SELECT MAX(trade_date) FROM board_daily").fetchone() if 'trade_date' in str(t.execute("PRAGMA table_info(board_daily)").fetchall()) else '?')
print("stock_info cols:", [r[1] for r in t.execute("PRAGMA table_info(stock_info)").fetchall()])
# check signals.db for industry
sig = sqlite3.connect(f'{BASE}/signals.db')
tabs = [r[0] for r in sig.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("signals tables:", tabs)
led = sqlite3.connect(f'{BASE}/ledger.db')
print("ledger tables:", [r[0] for r in led.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
