"""补TDX 2015-2023日线到stock.db（本地文件版）"""
import struct, os, duckdb, time
from pathlib import Path

TDX_SH = Path('/tmp/sh/lday')
TDX_SZ = Path('/tmp/sz/lday')
DB = Path.home() / '.hermes' / 'stockdb' / 'stock.db'
CUTOFF = '2024-01-01'

def parse_day(fpath):
    with open(fpath, 'rb') as f:
        data = f.read()
    n = len(data) // 32
    result = []
    for i in range(n):
        rec = data[i*32:(i+1)*32]
        dt, op, hi, lo, cl, am, vo, _ = struct.unpack('IIIIIIII', rec)
        if cl <= 0: continue
        y,m,d = dt//10000, (dt%10000)//100, dt%100
        ds = f'{y}-{m:02d}-{d:02d}'
        if ds >= CUTOFF: continue
        result.append((ds, op/100, hi/100, lo/100, cl/100, vo, am, (cl-op)/op*100))
    return result

con = duckdb.connect(str(DB))
have = set(r[0] for r in con.execute("SELECT DISTINCT stock_code FROM stock_daily").fetchall())
print(f"stock.db已有: {len(have)}只")

total = 0
t0 = time.time()
batch = []

for market, lday in [('sh', TDX_SH), ('sz', TDX_SZ)]:
    if not lday.is_dir(): continue
    for f in sorted(lday.iterdir()):
        if not f.name.endswith('.day'): continue
        code = f.name.replace('.day', '').replace(market, '')
        if code not in have: continue
        for rec in parse_day(str(f)):
            batch.append((code,) + rec)
        if len(batch) >= 100000:
            con.executemany("""
                INSERT OR IGNORE INTO stock_daily
                (stock_code, date, open, high, low, close, volume, amount, change_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            total += len(batch)
            batch = []
            print(f"  {total:,}条 ({time.time()-t0:.0f}s)", flush=True)

if batch:
    con.executemany("INSERT OR IGNORE INTO stock_daily VALUES (?,?,?,?,?,?,?,?,?)", batch)
    total += len(batch)

r = con.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM stock_daily").fetchone()
cnt = con.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
con.close()
print(f"\n完成! 插入{total:,}条, {time.time()-t0:.0f}s")
print(f"stock.db: {cnt}只, {r[2]:,}条, {str(r[0])[:10]}~{str(r[1])[:10]}")
