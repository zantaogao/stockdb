#!/usr/bin/env python3
"""
全量重建 v4 — 先全拉内存，再pandas批量写入
"""
import os, sys, time, duckdb, pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import threading

NEW_DB = os.path.expanduser("~/.hermes/stockdb/stock_clean.db")
OLD_DB = os.path.expanduser("~/.hermes/stockdb/stock.db")
MAX_WORKERS = 6
POSITIONS = [0, 800]

_results = {}
_results_lock = threading.Lock()

from pytdx.hq import TdxHq_API

def get_market(code):
    return 1 if code.startswith(('6', '9')) else 0

def init_db():
    db = duckdb.connect(NEW_DB)
    db.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            stock_code VARCHAR, date DATE,
            open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
            volume BIGINT, amount DOUBLE, change_pct DOUBLE
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS index_daily (
            index_code VARCHAR, date DATE,
            open DOUBLE, close DOUBLE, high DOUBLE, low DOUBLE,
            volume BIGINT, amount DOUBLE, change_pct DOUBLE
        )
    """)
    db.execute("CREATE TABLE IF NOT EXISTS build_progress (table_name VARCHAR PRIMARY KEY, total_rows BIGINT)")
    db.commit()
    db.close()

def get_a_share_codes():
    db = duckdb.connect(OLD_DB, read_only=True)
    codes = db.execute("""
        SELECT DISTINCT stock_code FROM stock_daily
        WHERE SUBSTR(stock_code, 1, 2) IN ('60', '68', '00', '30')
        ORDER BY stock_code
    """).fetchall()
    db.close()
    return sorted(set(c[0] for c in codes))

def fetch_one(code):
    api = TdxHq_API(heartbeat=False)
    try:
        if not api.connect('180.153.18.172', 80, time_out=8):
            return
        market = get_market(code)
        bars = {}
        for pos in POSITIONS:
            try:
                data = api.get_security_bars(9, market, code, pos, 800)
                if data:
                    for bar in data:
                        d = f"{bar['year']:04d}-{bar['month']:02d}-{bar['day']:02d}"
                        if d not in bars:
                            bars[d] = (
                                round(float(bar['open']), 2),
                                round(float(bar['close']), 2),
                                round(float(bar['high']), 2),
                                round(float(bar['low']), 2),
                                int(bar['vol']) * 100,
                                round(float(bar['amount']), 2),
                            )
            except:
                pass
        api.disconnect()
        if bars:
            with _results_lock:
                _results[code] = bars
    except:
        try: api.disconnect()
        except: pass

def rebuild_stock_daily(codes):
    print(f"\n📡 拉取 {len(codes)} 只股票 ({MAX_WORKERS}线程)...")
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one, c): c for c in codes}
        for _ in tqdm(as_completed(futures), total=len(codes), desc="拉取"):
            pass
    
    t1 = time.time()
    n_stocks = len(_results)
    print(f"✅ 拉取完成: {n_stocks}只, 耗时{t1-t0:.0f}s")
    
    # 转pandas DataFrame
    print(f"💾 构建DataFrame...")
    records = []
    for code in tqdm(_results, desc="处理"):
        bars = _results[code]
        prev_close = None
        for d in sorted(bars.keys()):
            o, c, h, l, v, a = bars[d]
            chg = round((c - prev_close) / prev_close * 100, 2) if (prev_close and prev_close > 0) else None
            records.append((code, d, o, c, h, l, v, a, chg))
            prev_close = c
    
    print(f"  共 {len(records):,} 行")
    
    df = pd.DataFrame(records, columns=['stock_code','date','open','close','high','low','volume','amount','change_pct'])
    del records  # 释放内存
    print(f"  DataFrame占用: {df.memory_usage(deep=True).sum()/1024/1024:.0f} MB")
    
    # 写入DB
    print(f"💾 写入DB (pandas to_sql)...")
    t2 = time.time()
    db = duckdb.connect(NEW_DB)
    db.execute("PRAGMA threads=4")
    
    # 分批写入，每批50万行
    for i in range(0, len(df), 500000):
        chunk = df.iloc[i:i+500000]
        db.execute("BEGIN TRANSACTION")
        db.executemany(
            "INSERT INTO stock_daily VALUES (?,?,?,?,?,?,?,?,?)",
            chunk.values.tolist()
        )
        db.execute("COMMIT")
        print(f"  已写入 {min(i+500000, len(df)):,}/{len(df):,} 行")
    
    db.execute("INSERT OR REPLACE INTO build_progress VALUES ('stock_daily', ?)", [len(df)])
    db.commit()
    db.close()
    
    print(f"✅ 写入完成: {len(df):,}行, 耗时{time.time()-t2:.0f}s")

def rebuild_index_daily():
    print("\n📡 拉取指数数据...")
    indexes = [
        (1, '000001', '上证指数'), (0, '399001', '深证成指'),
        (0, '399006', '创业板指'), (1, '000688', '科创50'),
        (1, '000300', '沪深300'), (1, '000016', '上证50'),
        (1, '000905', '中证500'), (0, '399852', '中证1000'),
    ]
    api = TdxHq_API(heartbeat=False)
    api.connect('180.153.18.172', 80, time_out=5)
    
    records = []
    for market, code, name in indexes:
        bars = {}
        for pos in POSITIONS:
            try:
                data = api.get_index_bars(9, market, code, pos, 800)
                if data:
                    for bar in data:
                        d = f"{bar['year']:04d}-{bar['month']:02d}-{bar['day']:02d}"
                        if d not in bars:
                            bars[d] = (round(float(bar['open']),2), round(float(bar['close']),2),
                                       round(float(bar['high']),2), round(float(bar['low']),2),
                                       int(bar['vol'])*100, round(float(bar['amount']),2))
            except:
                pass
        if bars:
            prev_close = None
            for d in sorted(bars.keys()):
                o, c, h, l, v, a = bars[d]
                chg = round((c - prev_close) / prev_close * 100, 2) if (prev_close and prev_close > 0) else None
                records.append((code, d, o, c, h, l, v, a, chg))
                prev_close = c
            print(f"  ✅ {name}: {len(bars)}条")
    
    api.disconnect()
    
    if records:
        df = pd.DataFrame(records, columns=['index_code','date','open','close','high','low','volume','amount','change_pct'])
        db = duckdb.connect(NEW_DB)
        db.executemany("INSERT INTO index_daily VALUES (?,?,?,?,?,?,?,?,?)", df.values.tolist())
        db.execute("INSERT OR REPLACE INTO build_progress VALUES ('index_daily', ?)", [len(df)])
        db.commit()
        db.close()
        print(f"✅ 指数完成: {len(df)}条")

def main():
    t0 = time.time()
    init_db()
    codes = get_a_share_codes()
    rebuild_stock_daily(codes)
    rebuild_index_daily()
    
    db = duckdb.connect(NEW_DB)
    sd = db.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    idx = db.execute("SELECT COUNT(*) FROM index_daily").fetchone()[0]
    sd_min = db.execute("SELECT MIN(date) FROM stock_daily").fetchone()[0]
    sd_max = db.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    stocks = db.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
    db.close()
    
    print(f"\n{'='*50}")
    print(f"🎉 重建完成! 耗时: {(time.time()-t0)/60:.1f}分钟")
    print(f"  stock_daily: {sd:,}条, {stocks}只股票")
    print(f"  日期范围: {sd_min} ~ {sd_max}")
    print(f"  index_daily: {idx:,}条")
    print(f"{'='*50}")

if __name__ == '__main__':
    main()
