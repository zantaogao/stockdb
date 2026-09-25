import duckdb, os, urllib.request as ur, sys
from datetime import datetime

DB_PATH = os.path.expanduser('~/.hermes/stockdb/tushare.db')
con = duckdb.connect(DB_PATH, read_only=True)
today_str = str(datetime.now().date())

# Check if watch pool exists for today
rows = con.execute(f"SELECT count(*) FROM daban_watch_pool WHERE scan_date='{today_str}'").fetchone()
print(f"[1] Watch pool rows (scan_date={today_str}): {rows[0]}")

# List all scan_dates in table
dates = con.execute("SELECT DISTINCT scan_date FROM daban_watch_pool ORDER BY 1 DESC LIMIT 5").fetchall()
print(f"[2] Recent scan_dates: {dates}")

if rows and rows[0] > 0:
    pool_rows = con.execute(f"SELECT stock_code, stock_name, limit_price, signal_sent FROM daban_watch_pool WHERE scan_date='{today_str}' LIMIT 3").fetchall()
    print(f"[3] Sample pool entries:")
    for r in pool_rows:
        print(f"   {r}")

# Test Sina API with a sample code
if rows and rows[0] > 0:
    codes = [r[0][:6] for r in con.execute(f"SELECT stock_code FROM daban_watch_pool WHERE scan_date='{today_str}' LIMIT 5").fetchall()]
    sina_list = ','.join([
        f"{'sh' if c.startswith(('6', '9')) else 'sz'}{c}"
        for c in codes
    ])
    url = f"https://hq.sinajs.cn/list={sina_list}"
    req = ur.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
    try:
        raw = ur.urlopen(req, timeout=5).read().decode('gbk')
        print(f"\n[4] Sina API response ({len(raw)} bytes):")
        for line in raw.strip().split('\n'):
            if 'hq_str_' in line:
                parts = line.split('"')[1].split(',')
                print(f"   {line[:60]}... price={parts[3]}, prev_close={parts[2]}")
    except Exception as e:
        print(f"[4] Sina error: {e}")

con.close()
