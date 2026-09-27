import sqlite3, duckdb
from pathlib import Path
BASE = Path.home()/'.hermes/stockdb'
db = sqlite3.connect(BASE/'signals.db')
dset = sorted({str(r[0]).replace('-','') for r in db.execute("SELECT DISTINCT score_date FROM shadow_40d_scores").fetchall()})
print('dset:', dset)
tdb = duckdb.connect(str(BASE/'tushare.db'), read_only=True)
cal = [str(r[0]) for r in tdb.execute("SELECT DISTINCT trade_date FROM daily ORDER BY 1").fetchall()]
cal_nodash = [d.replace('-','') for d in cal]
for d in dset:
    print(d, "in:", d in cal_nodash, "eval:", cal_nodash.index(d)+1 < len(cal_nodash), cal[cal_nodash.index(d)+1] if cal_nodash.index(d)+1 < len(cal_nodash) else None)
