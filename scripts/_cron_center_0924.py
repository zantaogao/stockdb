import sqlite3, os, duckdb, json
BASE = os.path.expanduser('~/.hermes/stockdb')
sc = sqlite3.connect(BASE + '/signals.db')
print('fusion_center_signals cols:', [r[1] for r in sc.execute("PRAGMA table_info(fusion_center_signals)")])
print('center rows last days:')
for r in sc.execute("SELECT * FROM fusion_center_signals ORDER BY rowid DESC LIMIT 3"):
    print(r)
print('center_dual date list:', sc.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM center_dual_ic_daily").fetchall())
