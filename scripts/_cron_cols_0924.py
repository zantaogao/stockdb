import sqlite3, os
sc = sqlite3.connect(os.path.expanduser('~/.hermes/stockdb/signals.db'))
print('signal_history:', [r[1] for r in sc.execute("PRAGMA table_info(signal_history)")])
print('ic_window:', [r[1] for r in sc.execute("PRAGMA table_info(ic_window)")])
