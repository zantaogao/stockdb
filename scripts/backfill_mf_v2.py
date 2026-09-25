#!/usr/bin/env python3
"""
AKShare资金流补全 v2 — 加重试、限速、持久连接
"""
import os, time, duckdb, argparse, random
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def fetch_one(code, prefix):
    """拉取单只股票，带重试"""
    import akshare as ak
    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.3, 0.8))  # 随机延迟避免限流
            df = ak.stock_individual_fund_flow(stock=code, market=prefix)
            if df is not None and len(df) > 0:
                records = []
                for _, row in df.iterrows():
                    records.append((
                        code,
                        str(row['日期']),
                        float(row['主力净流入-净额']) if pd.notna(row['主力净流入-净额']) else 0,
                        float(row['小单净流入-净额']) if pd.notna(row['小单净流入-净额']) else 0,
                        round(float(row['主力净流入-净占比']) if pd.notna(row['主力净流入-净占比']) else 0, 2),
                    ))
                return records
            return []
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                return []

def main(workers=5, max_stocks=None):
    conn = duckdb.connect(DB)
    stocks = conn.execute("""
        SELECT stock_code FROM stock_info 
        WHERE LEFT(stock_code, 3) != '920'
        ORDER BY stock_code
    """).fetchall()
    
    # 检查哪些股票已经拉满(>100条)，跳过
    have_data = set()
    for row in conn.execute("SELECT stock_code, COUNT(*) as c FROM money_flow WHERE date >= '2025-11-01' GROUP BY stock_code HAVING c > 100").fetchall():
        have_data.add(row[0])
    conn.close()
    
    all_codes = [s[0] for s in stocks if s[0] not in have_data]
    if max_stocks:
        all_codes = all_codes[:max_stocks]
    
    total = len(all_codes)
    print(f"需拉取: {total}只 (已跳过{len(have_data)}只已完备的)")
    print(f"并行 {workers} 路, 带随机延迟防限流\n")
    
    t0 = time.time()
    all_records = []
    done = 0
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for code in all_codes:
            prefix = 'sh' if code.startswith('6') else 'sz'
            futures[executor.submit(fetch_one, code, prefix)] = code
        
        for f in as_completed(futures):
            code = futures[f]
            records = f.result()
            done += 1
            if records:
                all_records.extend(records)
            if done % 50 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed * 60 if elapsed > 0 else 0
                print(f"  {done}/{total} ({done/total*100:.0f}%), {len(all_records)}条, {rate:.0f}只/分", flush=True)
    
    elapsed = time.time() - t0
    print(f"\n拉取完成: {done}只, {len(all_records)}条, {elapsed:.0f}s ({elapsed/60:.1f}分)")
    
    if all_records:
        print("写入数据库...")
        conn = duckdb.connect(DB)
        try:
            conn.execute("BEGIN TRANSACTION")
            batch_size = 0
            for r in all_records:
                conn.execute(
                    "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?, ?, ?, ?, ?)",
                    r
                )
                batch_size += 1
                if batch_size % 20000 == 0:
                    conn.execute("COMMIT")
                    conn.execute("BEGIN TRANSACTION")
                    print(f"  写入 {batch_size} 条...")
            conn.execute("COMMIT")
            
            # 统计
            r2 = conn.execute("""
                SELECT COUNT(DISTINCT date), COUNT(DISTINCT stock_code), COUNT(*),
                       MIN(date), MAX(date) FROM money_flow
            """).fetchone()
            print(f"✅ money_flow 当前: {r2[0]}个交易日, {r2[1]}只股票, {r2[2]}条")
            print(f"   范围: {r2[3]} ~ {r2[4]}")
        except Exception as e:
            conn.execute("ROLLBACK")
            print(f"❌ 写入失败: {e}")
        finally:
            conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=5, help='并行数(默认5)')
    parser.add_argument('--max', type=int, default=None, help='限制股票数')
    args = parser.parse_args()
    main(workers=args.workers, max_stocks=args.max)
