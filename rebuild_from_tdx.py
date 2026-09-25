#!/usr/bin/env python3
"""从通达信pytdx重建干净日K线数据库 v3"""
import os, sys, time, json, duckdb, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from pytdx.hq import TdxHq_API

NEW_DB = os.path.expanduser("~/.hermes/stockdb/stock_clean.db")
CODES_FILE = '/tmp/a_share_codes.json'
MAX_WORKERS = 6

# 单连接（确保不冲突）
db = duckdb.connect(NEW_DB)

def create_tables():
    db.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            stock_code VARCHAR, date DATE,
            open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
            volume BIGINT, amount DOUBLE,
            amplitude DOUBLE, change_pct DOUBLE, turn_rate DOUBLE
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_sd_code ON stock_daily(stock_code)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_sd_date ON stock_daily(date)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS stock_info (
            stock_code VARCHAR PRIMARY KEY,
            name VARCHAR, market INTEGER
        )
    """)
    db.commit()

# 线程安全的TDX API
_tlocal = threading.local()
def get_api():
    if not hasattr(_tlocal, 'api') or _tlocal.api is None:
        _tlocal.api = TdxHq_API(heartbeat=False)
        _tlocal.api.connect('180.153.18.172', 80, time_out=5)
    return _tlocal.api

def fetch_all_bars(code, market):
    api = get_api()
    all_bars = []
    for start in [0, 800, 1600]:
        try:
            bars = api.get_security_bars(9, market, code, start, 800)
            if bars and len(bars) > 0:
                all_bars.extend(bars)
                if len(bars) < 800:
                    break
            else:
                break
        except:
            break
    return code, all_bars

def main():
    with open(CODES_FILE) as f:
        codes = json.load(f)
    print(f"📋 {len(codes)}只股票")

    create_tables()
    
    # stock_info
    db.execute("BEGIN TRANSACTION")
    for code in codes:
        market = 1 if code.startswith(('6', '68', '689')) else 0
        db.execute("INSERT OR IGNORE INTO stock_info VALUES (?, ?, ?)", [code, '', market])
    db.execute("COMMIT")

    BATCH = 200
    total_rows = 0
    
    for batch_start in range(0, len(codes), BATCH):
        batch = codes[batch_start:batch_start + BATCH]
        results = {}
        
        n = batch_start // BATCH + 1
        total_batches = (len(codes) + BATCH - 1) // BATCH
        print(f"\n📡 第{n}/{total_batches}批 ({batch_start+1}-{batch_start+len(batch)})...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for code in batch:
                m = 1 if code.startswith(('6', '68', '689')) else 0
                futures[executor.submit(fetch_all_bars, code, m)] = code
            for f in tqdm(as_completed(futures), total=len(batch), desc="TDX"):
                code, bars = f.result()
                if bars:
                    results[code] = bars
        
        rows = []
        for code, bars in results.items():
            for bar in sorted(bars, key=lambda x: (x['year'], x['month'], x['day'])):
                d = f"{bar['year']:04d}-{bar['month']:02d}-{bar['day']:02d}"
                rows.append((code, d, bar['open'], bar['close'], bar['high'], bar['low'],
                           bar['vol'] * 100, bar['amount'], None, None, None))
        
        if rows:
            # DuckDB原生pandas批量插入（比row-by-row快1000倍）
            import pandas as pd
            cols = ['stock_code','date','open','close','high','low','volume','amount','amplitude','change_pct','turn_rate']
            df = pd.DataFrame(rows, columns=cols)
            db.execute("INSERT INTO stock_daily SELECT * FROM df")
            db.commit()
        
        total_rows += len(rows)
        stks = db.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
        cnt = db.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
        print(f"  📊 {cnt:,}行, {stks}只股票")
    
    db.execute("CHECKPOINT")
    
    final = {
        'rows': db.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0],
        'stocks': db.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0],
        'min_date': db.execute("SELECT MIN(date) FROM stock_daily").fetchone()[0],
        'max_date': db.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0],
    }
    db.close()
    
    print(f"\n{'='*50}")
    print(f"✅ 重建完成!")
    print(f"  股票: {final['stocks']}只")
    print(f"  行数: {final['rows']:,}")
    print(f"  日期: {final['min_date']} ~ {final['max_date']}")
    print(f"{'='*50}")

if __name__ == '__main__':
    main()
