#!/usr/bin/env python3
"""盘后复盘数据采集 — DuckDB修正版"""
import subprocess, json, os, sys
from datetime import datetime

BASE = "/Users/zantao/.hermes/stockdb"
DB = os.path.join(BASE, "stock.db")
HOLDINGS = os.path.join(BASE, "holdings.json")
today = datetime.now().strftime("%Y-%m-%d")

# 1. Load holdings
with open(HOLDINGS) as f:
    data = json.load(f)
positions = data.get("positions", [])

hold = [p for p in positions if p.get("status") == "hold"]
watch_active = [p for p in positions if p.get("status") == "watch_active"]
watch_cold = [p for p in positions if p.get("status") == "watch_cold"]

print(f"STATUS|hold={len(hold)}|wa={len(watch_active)}|wc={len(watch_cold)}")

all_codes = set()
for p in watch_active + watch_cold:
    c = p.get("code", "")
    if c and not c.startswith("TRUST"):
        all_codes.add(c)

if not all_codes:
    print("NO_CODES")
    sys.exit(0)

codes_list = sorted(all_codes)
codes_str = "','".join(codes_list)
print(f"CODES|{','.join(codes_list)}")

def duck_sql(sql):
    r = subprocess.run(["duckdb", DB, "-csv", "-c", sql], capture_output=True, text=True, timeout=30)
    lines = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
    # Skip DuckDB header line (first line is always the CSV header)
    if lines and lines[0].startswith('"') or lines and lines[0].startswith('stock') or lines and lines[0].startswith('index'):
        pass  # keep header, we'll handle it
    return lines

# 2. Latest DB date
r = subprocess.run(["duckdb", DB, "-csv", "-c", 
    f"SELECT MAX(date)::VARCHAR FROM stock_daily WHERE stock_code IN ('{codes_str}')"],
    capture_output=True, text=True, timeout=10)
lines = [l.strip() for l in r.stdout.strip().split('\n') if l.strip()]
latest_db_date = lines[-1].strip('"') if lines else "unknown"
print(f"LATEST_DB_DATE|{latest_db_date}")

# 3. Latest prices & changes
r = subprocess.run(["duckdb", DB, "-csv", "-c",
    f"""
    WITH latest AS (
        SELECT stock_code, close, amount, volume, change_pct,
               LAG(close, 1) OVER (PARTITION BY stock_code ORDER BY date) AS prev_close
        FROM stock_daily
        WHERE stock_code IN ('{codes_str}')
          AND date = (SELECT MAX(date) FROM stock_daily WHERE stock_code IN ('{codes_str}'))
    )
    SELECT stock_code, close, 
           COALESCE(ROUND(change_pct, 2), ROUND((close/NULLIF(prev_close,0)-1)*100, 2)) AS chg,
           ROUND(amount/1e8, 2) AS amount_yi
    FROM latest
    ORDER BY stock_code
    """],
    capture_output=True, text=True, timeout=15)
for line in r.stdout.strip().split('\n'):
    line = line.strip()
    if line and not line.startswith('stock_code'):
        print(f"PRICE|{line}")

# 4. MA60
r = subprocess.run(["duckdb", DB, "-csv", "-c",
    f"""
    SELECT stock_code, ROUND(AVG(close), 2) AS ma60
    FROM stock_daily
    WHERE stock_code IN ('{codes_str}')
      AND date >= (SELECT MAX(date) FROM stock_daily WHERE stock_code IN ('{codes_str}')) - INTERVAL '60 days'
    GROUP BY stock_code
    ORDER BY stock_code
    """],
    capture_output=True, text=True, timeout=15)
for line in r.stdout.strip().split('\n'):
    line = line.strip()
    if line and not line.startswith('stock_code'):
        print(f"MA60|{line}")

# 5. MA120
r = subprocess.run(["duckdb", DB, "-csv", "-c",
    f"""
    SELECT stock_code, ROUND(AVG(close), 2) AS ma120
    FROM stock_daily
    WHERE stock_code IN ('{codes_str}')
      AND date >= (SELECT MAX(date) FROM stock_daily WHERE stock_code IN ('{codes_str}')) - INTERVAL '120 days'
    GROUP BY stock_code
    ORDER BY stock_code
    """],
    capture_output=True, text=True, timeout=15)
for line in r.stdout.strip().split('\n'):
    line = line.strip()
    if line and not line.startswith('stock_code'):
        print(f"MA120|{line}")

# 6. Stock names
r = subprocess.run(["duckdb", DB, "-csv", "-c",
    f"SELECT stock_code, short_name FROM stock_info WHERE stock_code IN ('{codes_str}') ORDER BY stock_code"],
    capture_output=True, text=True, timeout=10)
for line in r.stdout.strip().split('\n'):
    line = line.strip()
    if line and not line.startswith('stock_code'):
        print(f"NAME|{line}")

# 7. Money flow (20-day main_net)
r = subprocess.run(["duckdb", DB, "-csv", "-c",
    f"""
    SELECT stock_code, 
           ROUND(COALESCE(SUM(main_net), 0), 0) AS main_net_20d
    FROM money_flow
    WHERE stock_code IN ('{codes_str}')
      AND date >= (SELECT MAX(date) FROM stock_daily WHERE stock_code IN ('{codes_str}')) - INTERVAL '20 days'
    GROUP BY stock_code
    ORDER BY stock_code
    """],
    capture_output=True, text=True, timeout=15)
for line in r.stdout.strip().split('\n'):
    line = line.strip()
    if line and not line.startswith('stock_code'):
        print(f"MF|{line}")

# 8. Index data
r = subprocess.run(["duckdb", DB, "-csv", "-c",
    """
    WITH idx_latest AS (
        SELECT index_code, date, close,
               LAG(close, 1) OVER (PARTITION BY index_code ORDER BY date) AS prev_close,
               LAG(close, 60) OVER (PARTITION BY index_code ORDER BY date) AS close_60d
        FROM index_daily
        WHERE index_code IN ('000001.SH', '399001.SZ', '399006.SZ')
        ORDER BY date DESC
        LIMIT 9
    )
    SELECT index_code, close,
           ROUND((close / NULLIF(prev_close,0) - 1) * 100, 2) AS chg_pct,
           ROUND((close / NULLIF(close_60d,0) - 1) * 100, 2) AS ma60_dev
    FROM idx_latest
    WHERE prev_close IS NOT NULL
    """],
    capture_output=True, text=True, timeout=10)
for line in r.stdout.strip().split('\n'):
    line = line.strip()
    if line and not line.startswith('index_code'):
        print(f"INDEX|{line}")

# 9. Sina API (same as before)
import urllib.request
sina_codes = []
for code in codes_list:
    if code.startswith(('0', '3')):
        sina_codes.append(f"sz{code}")
    elif code.startswith(('6')):
        sina_codes.append(f"sh{code}")
sina_codes.extend(['sh000001', 'sz399001', 'sz399006'])
sina_url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
req = urllib.request.Request(sina_url, headers={
    'Referer': 'https://finance.sina.com.cn',
    'User-Agent': 'Mozilla/5.0'
})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    sina_raw = resp.read().decode('gbk', errors='replace')
    for line in sina_raw.strip().split('\n'):
        line = line.strip()
        if not line or '=' not in line:
            continue
        try:
            var_part = line.split('hq_str_')[1].split('=')[0]
            data_part = line.split('"')[1]
            fields = data_part.split(',')
            sina_code = var_part[2:]
            name = fields[0]
            current = float(fields[3]) if len(fields) > 3 and fields[3] else None
            prev_close = float(fields[2]) if len(fields) > 2 and fields[2] else None
            if current and prev_close:
                chg_pct = round((current / prev_close - 1) * 100, 2)
            else:
                chg_pct = None
            if current:
                print(f"SINA|{sina_code}|{name}|{current}|{chg_pct}")
        except (IndexError, ValueError):
            pass
except Exception as e:
    print(f"SINA_ERR|{str(e)}")

# 10. Trade log
trade_log = os.path.join(BASE, "model_watch_trades.json")
if os.path.exists(trade_log):
    with open(trade_log) as f:
        try:
            trades = json.load(f)
            recent = trades[-5:] if len(trades) > 5 else trades
            for t in recent:
                print(f"TRADE|{json.dumps(t, ensure_ascii=False)}")
        except:
            pass

print("DONE")
