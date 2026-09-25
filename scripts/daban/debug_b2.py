import duckdb, os, urllib.request as ur
from datetime import datetime

DB_PATH = os.path.expanduser('~/.hermes/stockdb/tushare.db')
con = duckdb.connect(DB_PATH, read_only=True)
today_str = str(datetime.now().date())

# Get all codes from today's pool
pool_rows = con.execute(f"SELECT stock_code FROM daban_watch_pool WHERE scan_date='{today_str}'").fetchall()
codes = [r[0][:6] for r in pool_rows]
print(f"[1] Codes from pool: {codes}")

# Build Sina URL properly - handle BJ codes
sina_list = []
for c in codes:
    if c.startswith('9') or c.startswith('6'):
        sina_list.append(f"sh{c}")
    elif c.startswith('0') or c.startswith('3') or c.startswith('2'):
        sina_list.append(f"sz{c}")
    else:
        # e.g. 920857 is Beijing exchange, try sh
        sina_list.append(f"sh{c}")

print(f"[2] Sina list: {','.join(sina_list)}")

url = f"https://hq.sinajs.cn/list={','.join(sina_list)}"
req = ur.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
raw = ur.urlopen(req, timeout=5).read().decode('gbk')
print(f"\n[3] Raw response ({len(raw)} bytes):")
for line in raw.strip().split('\n'):
    print(f"   {line[:120]}")

# Try parsing one manually
lines = [l for l in raw.strip().split('\n') if 'hq_str_' in l and '=""' not in l]
print(f"\n[4] Valid lines: {len(lines)}")
for line in lines[:3]:
    parts = line.split('"')[1].split(',')
    scode = line.split('=')[0].replace('var hq_str_', '')
    print(f"   code={scode}, name={parts[0]}, price={parts[3] if len(parts)>3 else 'N/A'}, prev_close={parts[2] if len(parts)>2 else 'N/A'}")

con.close()
