#!/usr/bin/env python3
import sqlite3
sdb = sqlite3.connect("/Users/zantao/.hermes/stockdb/state.db")
cols = sdb.execute("PRAGMA table_info(fusion_3f_signals)").fetchall()
print("fusion_3f_signals columns:", [c[1] for c in cols])
# find the date-like column
date_col = None
for c in cols:
    if "date" in c[1].lower():
        date_col = c[1]
        break
print("date-like col:", date_col)
if date_col:
    latest = sdb.execute(f"SELECT MAX(REPLACE({date_col},'-','')) FROM fusion_3f_signals").fetchone()[0]
    print(f"latest {date_col}={latest}")
    dist = sdb.execute(f"SELECT signal, COUNT(*) FROM fusion_3f_signals WHERE REPLACE({date_col},'-','')=? GROUP BY 1", [latest]).fetchall()
    print("dist:", dict(dist))
sdb.close()
