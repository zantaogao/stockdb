"""从TDX批量导入日线数据到stock.db（补缺3623只）"""
import struct, os, duckdb, time
from datetime import datetime

TDX_BASE = os.path.expanduser('~/Desktop/PC_C/zd_gfzq_new/vipdoc')
STOCK_DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def parse_day(fpath):
    """解析TDX .day文件，返回[(date_str, open, high, low, close, amount, volume), ...]"""
    with open(fpath, 'rb') as f:
        data = f.read()
    if not data: return []
    rec_size = 32
    records = len(data) // rec_size
    result = []
    for i in range(records):
        rec = data[i*rec_size:(i+1)*rec_size]
        dt, op, hi, lo, cl, am, vo, _ = struct.unpack('IIIIIIII', rec)
        y, m, d = dt//10000, (dt%10000)//100, dt%100
        result.append((f'{y}-{m:02d}-{d:02d}',
                       op/100, hi/100, lo/100, cl/100,
                       am, vo))
    return result

def get_market(code):
    if code.startswith(('6','68','900')): return 'sh'
    if code.startswith(('0','3','2')): return 'sz'
    if code.startswith(('4','8')): return 'bj'
    return None

# ── 1. 找出TDX有但DB缺的股票 ──
print("扫描TDX文件列表...")
tdx_codes = {}
for market in ['sh', 'sz', 'bj']:
    lday = os.path.join(TDX_BASE, market, 'lday')
    if not os.path.isdir(lday): continue
    for f in os.listdir(lday):
        if not f.endswith('.day'): continue
        code = f.replace('.day','').replace(market,'')
        tdx_codes[code] = market

print(f"TDX: {len(tdx_codes)}只")

con = duckdb.connect(STOCK_DB)
db_codes = set(r[0] for r in con.execute("SELECT DISTINCT stock_code FROM stock_daily").fetchall())
print(f"stock.db: {len(db_codes)}只")

to_import = [c for c in sorted(tdx_codes.keys()) if c not in db_codes]
print(f"待导入: {len(to_import)}只")

if not to_import:
    print("没有需要导入的股票。")
    con.close()
    exit()

# ── 2. 批量导入 ──
print(f"\n开始导入 {len(to_import)} 只股票...")
t0 = time.time()
inserted = 0
batch = []

for i, code in enumerate(to_import):
    market = tdx_codes[code]
    fpath = os.path.join(TDX_BASE, market, 'lday', f'{market}{code}.day')
    if not os.path.exists(fpath): continue
    
    records = parse_day(fpath)
    for date_str, op, hi, lo, cl, am, vo in records:
        if op <= 0 or cl <= 0: continue
        change_pct = (cl - op) / op * 100
        batch.append((code, date_str, op, hi, lo, cl, vo, am, change_pct))
    
    if len(batch) >= 50000:
        con.executemany("""
            INSERT OR IGNORE INTO stock_daily 
            (stock_code, date, open, high, low, close, volume, amount, change_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        inserted += len(batch)
        batch = []
    
    if (i+1) % 200 == 0 or i == len(to_import)-1:
        print(f"  {i+1}/{len(to_import)} 已插入{inserted:,}条 ({time.time()-t0:.0f}s)")

# 最后一批
if batch:
    con.executemany("""
        INSERT OR IGNORE INTO stock_daily 
        (stock_code, date, open, high, low, close, volume, amount, change_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, batch)
    inserted += len(batch)

elapsed = time.time() - t0
print(f"\n{'='*50}")
print(f"导入完成!")
print(f"  股票: {len(to_import)}只")
print(f"  记录: {inserted:,}条")
print(f"  耗时: {elapsed:.0f}s ({inserted/elapsed:.0f}条/秒)")

# ── 3. 验证 ──
new_cnt = con.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
total_rows = con.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
latest = con.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
print(f"\nstock.db现在: {new_cnt}只, {total_rows:,}条记录")
print(f"最新日期: {latest}")
con.close()
