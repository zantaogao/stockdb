#!/usr/bin/env python3
"""Retrain-need check part 2: IC performance from state.db (SQLite)."""
import sqlite3, sys
from pathlib import Path
from datetime import datetime

BASE = Path.home() / '.hermes' / 'stockdb'
con = sqlite3.connect(str(BASE / 'state.db'))
con.row_factory = sqlite3.Row

def show_table(name, limit=8):
    cur = con.execute(f"SELECT * FROM {name} ORDER BY rowid DESC LIMIT {limit}")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print(f"--- {name} (cols: {cols}) ---")
    for r in rows:
        print("  ", tuple(r))
    print()

# ic_daily: model-level daily IC
cur = con.execute("SELECT COUNT(*) FROM ic_daily")
print("ic_daily total rows:", cur.fetchone()[0])
show_table('ic_daily')

# rolling stats over recent rows
cur = con.execute("SELECT * FROM ic_daily ORDER BY rowid DESC LIMIT 60")
rows = [dict(r) for r in cur.fetchall()]
if rows:
    # find the date column
    keys = rows[0].keys()
    date_key = 'signal_date' if 'signal_date' in keys else (list(keys)[0])
    print(f"date_key={date_key}, newest={rows[0][date_key]}, oldest60={rows[-1][date_key]}")
    model_keys = [k for k in ('reg10','reg20','reg40','fusion','ic10','ic20','ic40') if k in keys]
    import statistics
    for win in (20, 60):
        window = rows[:win]
        vals = {k: [r[k] for r in window if r.get(k) is not None] for k in model_keys}
        line = f"近{win}日: "
        for k in model_keys:
            v = vals[k]
            if v:
                line += f"{k}={sum(v)/len(v):+.4f} (n={len(v)})  "
        print(line)
    print()

# factor_ic_roll: fusion + factor rolling IC
try:
    cur = con.execute("""
        SELECT as_of_date, factor_name, mean_ic, ic_ir, win_rate, window
        FROM factor_ic_roll ORDER BY as_of_date DESC LIMIT 12""")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    print("--- factor_ic_roll 最新 12 行 ---")
    for r in rows:
        print("  ", tuple(r))
except Exception as e:
    print("factor_ic_roll err:", e)
print()

# fusion_ic_daily
try:
    show_table('fusion_ic_daily')
except Exception as e:
    print("fusion_ic_daily err:", e)

con.close()
