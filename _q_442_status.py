#!/usr/bin/env /usr/bin/python3 -B
"""442影子链现状: ic_shadow_442 表盘点"""
import sqlite3, statistics, math
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
cols = [r[1] for r in c.execute("PRAGMA table_info(ic_shadow_442)").fetchall()]
print("列:", cols)
rows = c.execute("SELECT * FROM ic_shadow_442 ORDER BY 1").fetchall()
print("行数:", len(rows))
if rows:
    print("首日:", rows[0], "\n末日:", rows[-1])
import json
# 打印列名+逐日数据到csv
import csv, io
with open('/tmp/ic442.csv','w',newline='') as f:
    w = csv.writer(f); w.writerow(cols)
    for r in rows: w.writerow(r)
print("存 /tmp/ic442.csv")
