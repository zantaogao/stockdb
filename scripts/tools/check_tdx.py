"""TDX .day 文件解析 + stock.db 交叉对比"""
import os, struct, duckdb
from datetime import datetime

TDX_BASE = os.path.expanduser('~/Desktop/PC_C/zd_gfzq_new/vipdoc')
STOCK_DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def parse_day(fpath):
    """解析TDX .day文件，返回[(date_str, open, high, low, close, amount, volume), ...]"""
    with open(fpath, 'rb') as f:
        data = f.read()
    rec_size = 32
    records = len(data) // rec_size
    result = []
    for i in range(records):
        rec = data[i*rec_size:(i+1)*rec_size]
        dt, op, hi, lo, cl, am, vo, _ = struct.unpack('IIIIIIII', rec)
        # dt format: YYYYMMDD
        y, m, d = dt//10000, (dt%10000)//100, dt%100
        result.append((f'{y}-{m:02d}-{d:02d}',
                       op/100, hi/100, lo/100, cl/100,
                       am, vo))
    return result

def tdx_code_to_std(tdx_code, market):
    """TDX文件名转标准代码，如 sh600519 -> 600519, sz000001 -> 000001"""
    code = tdx_code.replace('.day','')
    if code.startswith('sh'): return code[2:]
    if code.startswith('sz'): return code[2:]
    if code.startswith('bj'): return code[2:]
    return code

# ── 1. TDX统计 ──
print("="*60)
print("TDX数据统计")
print("="*60)

tdx_stocks = {}  # code -> market
for market in ['sh', 'sz', 'bj']:
    lday = os.path.join(TDX_BASE, market, 'lday')
    if not os.path.isdir(lday): continue
    for f in os.listdir(lday):
        if not f.endswith('.day'): continue
        code = tdx_code_to_std(f, market)
        tdx_stocks[code] = market

print(f"总股票数: {len(tdx_stocks)}")
print(f"  沪市: {sum(1 for v in tdx_stocks.values() if v=='sh')}")
print(f"  深市: {sum(1 for v in tdx_stocks.values() if v=='sz')}")
print(f"  北交所: {sum(1 for v in tdx_stocks.values() if v=='bj')}")

# ── 2. stock.db覆盖检查 ──
print("\n" + "="*60)
print("stock.db覆盖检查")
print("="*60)

con = duckdb.connect(STOCK_DB, read_only=True)
db_codes = set(r[0] for r in con.execute("SELECT DISTINCT stock_code FROM stock_daily").fetchall())

tdx_only = tdx_stocks.keys() - db_codes
db_only = db_codes - tdx_stocks.keys()
both = tdx_stocks.keys() & db_codes

print(f"stock.db: {len(db_codes)}只")
print(f"TDX有·DB无: {len(tdx_only)}只")
print(f"DB有·TDX无: {len(db_only)}只")
print(f"交集: {len(both)}只")

#  展示TDX有但DB缺的股票样例
if tdx_only:
    print(f"\nTDX有但DB缺（前20只）:")
    for code in sorted(tdx_only)[:20]:
        m = tdx_stocks[code]
        fpath = os.path.join(TDX_BASE, m, 'lday', f'{m}{code}.day')
        recs = parse_day(fpath)
        if recs:
            print(f"  {code}({m}): {len(recs)}条, {recs[0][0]}~{recs[-1][0]}")
        else:
            print(f"  {code}({m}): 0条")

# ── 3. 数据日期比对 ──
print("\n" + "="*60)
print("日期范围比对（抽样10只）")
print("="*60)

test_codes = ['600519','300750','000001','601318','000333','002415','688981','600036','000858','002714']
for code in test_codes:
    if code not in tdx_stocks: continue
    m = tdx_stocks[code]
    fpath = os.path.join(TDX_BASE, m, 'lday', f'{m}{code}.day')
    tdx_recs = parse_day(fpath)
    if not tdx_recs: continue
    db_latest = con.execute(f"SELECT MAX(date), MIN(date), COUNT(*) FROM stock_daily WHERE stock_code='{code}'").fetchone()
    tdx_latest = tdx_recs[-1][0]
    tdx_earliest = tdx_recs[0][0]
    print(f"  {code}: TDX {tdx_earliest}~{tdx_latest} ({len(tdx_recs)}条) | DB {db_latest[1]}~{db_latest[0]} ({db_latest[2]}条)")

# ── 4. 收盘价核对（抽查最近20天） ──
print("\n" + "="*60)
print("收盘价核对（600519茅台，最近20天）")
print("="*60)

code = '600519'
m = tdx_stocks[code]
tdx_recs = parse_day(os.path.join(TDX_BASE, m, 'lday', f'{m}{code}.day'))
tdx_dict = {r[0]: r[4] for r in tdx_recs}  # date -> close
db_rows = con.execute(f"SELECT date, close FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 20").fetchall()

differences = 0
for dr in reversed(db_rows):
    db_date = str(dr[0])[:10]
    db_close = float(dr[1])
    tdx_close = tdx_dict.get(db_date)
    if tdx_close:
        diff = abs(db_close - tdx_close)/tdx_close*100
        flag = '⚠️' if diff > 0.5 else '✓'
        if diff > 0.5: differences += 1
        print(f"  {db_date}: TDX={tdx_close:.2f}  DB={db_close:.2f}  diff={diff:.2f}% {flag}")
    else:
        print(f"  {db_date}: TDX=无数据  DB={db_close:.2f}  ❌")

print(f"\n差异>0.5%的交易日: {differences}/20")

con.close()
