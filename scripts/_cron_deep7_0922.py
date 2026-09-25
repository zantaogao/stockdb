#!/usr/bin/env python3
import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
cols=[c[1] for c in led.execute("PRAGMA table_info(strategy_positions)").fetchall()]
print(cols)
for r in led.execute("SELECT * FROM strategy_positions WHERE status='hold' OR status IS NULL").fetchall():
    print(str(r)[:170])
