#!/usr/bin/env python3
import duckdb
from pathlib import Path

state_db = Path.home() / '.hermes' / 'stockdb' / 'state.db'
con = duckdb.connect(str(state_db), read_only=True)

# 查最新日期
r = con.execute('SELECT MAX(date) FROM signal_history').fetchone()[0]
print('Latest date:', r)

# 查该日期数量
count = con.execute('SELECT COUNT(*) FROM signal_history WHERE date = ?', (r,)).fetchone()[0]
print('Count on latest date:', count)

# 最近 5 个日期
print('\nRecent dates:')
for row in con.execute('SELECT date, COUNT(*) FROM signal_history GROUP BY date ORDER BY date DESC LIMIT 5').fetchall():
    print(f'  {row[0]}: {row[1]} records')

con.close()
