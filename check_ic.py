#!/usr/bin/env python3
import duckdb
from pathlib import Path

state_db = Path.home() / '.hermes' / 'stockdb' / 'state.db'
con = duckdb.connect(str(state_db), read_only=True)

print('IC 记录 (最近 3 条):')
for row in con.execute('SELECT * FROM ic_daily ORDER BY calc_date DESC LIMIT 3').fetchall():
    print(row)

con.close()
