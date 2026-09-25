import duckdb, os, urllib.request as ur
from datetime import datetime

DB_PATH = os.path.expanduser('~/.hermes/stockdb/tushare.db')
con = duckdb.connect(DB_PATH, read_only=True)
today_str = str(datetime.now().date())

# Get all codes from today's pool
pool_rows = con.execute(f"SELECT stock_code, stock_name, industry, limit_price FROM daban_watch_pool WHERE scan_date='{today_str}' AND signal_sent IS NOT TRUE").fetchall()
pool_info = {r[0]: r for r in pool_rows}
codes = [r[0][:6] for r in pool_rows]

# Build Sina URL
sina_list = []
for c in codes:
    if c.startswith('9') or c.startswith('6'):
        sina_list.append(f"sh{c}")
    else:
        sina_list.append(f"sz{c}")

url = f"https://hq.sinajs.cn/list={','.join(sina_list)}"
req = ur.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
raw = ur.urlopen(req, timeout=5).read().decode('gbk')

signals = []
for line in raw.strip().split('\n'):
    if 'hq_str_' not in line or '=""' in line:
        continue
    parts = line.split('"')[1].split(',')
    scode = line.split('=')[0].replace('var hq_str_', '')
    code_clean = scode[2:]  # remove sh/sz prefix
    
    ts_code = f"{code_clean}.SH" if code_clean.startswith(('6', '9')) else f"{code_clean}.SZ"
    
    current_price = float(parts[3])
    prev_close = float(parts[2])
    change_pct = (current_price - prev_close) / prev_close * 100
    
    if ts_code not in pool_info:
        continue
    
    info = pool_info[ts_code]
    limit_price = info[3]  # yesterday's close/limit price from daily
    
    print(f"[{code_clean}] {info[1]:<6} price={current_price:.2f} prev_close={prev_close:.3f} change_pct={change_pct:+.1f}%")
    
    if change_pct >= 5:
        # Calculate score
        score = 0
        reasons = []
        
        # 1. change pct (max 30)
        if change_pct >= 9.8:
            score += 30; reasons.append('涨停')
        elif change_pct >= 7:
            score += int(10 + (change_pct - 7) / 2.8 * 20); reasons.append(f'涨{change_pct:.1f}%')
        else:
            score += int(change_pct / 10 * 10)
        
        # 2. break through yesterday's close (max 15)
        open_diff = (current_price - limit_price) / limit_price * 100 if limit_price else 0
        if open_diff > 3:
            score += 15; reasons.append(f'突破昨收+{open_diff:.1f}%')
        elif open_diff > 1:
            score += 10; reasons.append(f'突破昨收+{open_diff:.1f}%')
        
        # 3. turnover (max 20) - from pool info
        turnover = pool_info.get(ts_code, [None]*7)[6] if len(pool_info.get(ts_code, [])) > 6 else None
        
        # 4. market cap (max 20) 
        mv_yi = pool_info.get(ts_code, [None]*5)[4] if len(pool_info.get(ts_code, [])) > 4 else 0
        
        print(f"   -> change_pct={change_pct:.1f}% >=5? YES | score so far: {score} | reasons: {reasons}")

con.close()
