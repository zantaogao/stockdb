#!/usr/bin/env python3
"""
用AKShare批量补全资金流数据
策略：逐只股票拉取约120天历史，写入money_flow表
并行20路，预计 ~15-20分钟
"""
import os, sys, time, duckdb, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def fetch_stock_mf(code, prefix='sz'):
    """拉取单只股票的资金流历史"""
    import akshare as ak
    try:
        df = ak.stock_individual_fund_flow(stock=code, market=prefix)
        if df is None or len(df) == 0:
            return []
        records = []
        for _, row in df.iterrows():
            date_str = row['日期']
            main_net = float(row['主力净流入-净额']) if pd.notna(row['主力净流入-净额']) else 0
            retail_net = float(row['小单净流入-净额']) if pd.notna(row['小单净流入-净额']) else 0
            main_pct = float(row['主力净流入-净占比']) if pd.notna(row['主力净流入-净占比']) else 0
            records.append((code, date_str, main_net, retail_net, round(main_pct, 2)))
        return records
    except Exception as e:
        return []

def batch_import(records, batch_size=50000):
    """批量写入数据库"""
    conn = duckdb.connect(DB)
    try:
        conn.execute("BEGIN TRANSACTION")
        inserted = 0
        for code, dt, mn, rn, mp in records:
            # dt是字符串YYYY-MM-DD
            conn.execute(
                "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?, ?, ?, ?, ?)",
                [code, dt, mn, rn, mp],
            )
            inserted += 1
            if inserted % batch_size == 0:
                conn.execute("COMMIT")
                conn.execute("BEGIN TRANSACTION")
                print(f"  已写入 {inserted} 条...", flush=True)
        conn.execute("COMMIT")
        return inserted
    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"  批量写入失败: {e}")
        return 0
    finally:
        conn.close()

def main(workers=20, max_stocks=None):
    import pandas as pd
    global pd
    
    conn = duckdb.connect(DB)
    stocks = conn.execute("""
        SELECT stock_code FROM stock_info 
        WHERE LEFT(stock_code, 3) != '920'
        ORDER BY stock_code
    """).fetchall()
    conn.close()
    
    all_codes = [s[0] for s in stocks]
    if max_stocks:
        all_codes = all_codes[:max_stocks]
    
    total = len(all_codes)
    print(f"计划拉取 {total} 只股票的资金流数据，并行 {workers} 路")
    
    t0 = time.time()
    all_records = []
    done = 0
    errors = 0
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for code in all_codes:
            prefix = 'sh' if code.startswith('6') else 'sz'
            futures[executor.submit(fetch_stock_mf, code, prefix)] = code
        
        for f in as_completed(futures):
            code = futures[f]
            records = f.result()
            done += 1
            if records:
                all_records.extend(records)
                if done % 100 == 0:
                    elapsed = time.time() - t0
                    rate = done / elapsed * 60
                    print(f"  进度: {done}/{total} ({done/total*100:.0f}%), 已获取{len(all_records)}条, {rate:.0f}只/分钟", flush=True)
            else:
                errors += 1
                if errors < 5:
                    print(f"  ⚠️ {code} 拉取失败")
    
    elapsed = time.time() - t0
    print(f"\n拉取完成: {done}只成功, {errors}只失败, 耗时{elapsed:.0f}s ({elapsed/60:.1f}分)")
    print(f"共获取 {len(all_records)} 条资金流记录")
    
    if all_records:
        print("写入数据库...")
        inserted = batch_import(all_records)
        
        conn = duckdb.connect(DB)
        r = conn.execute("""
            SELECT COUNT(DISTINCT date), COUNT(DISTINCT stock_code), COUNT(*),
                   MIN(date), MAX(date) FROM money_flow
        """).fetchone()
        conn.close()
        print(f"✅ 完成! money_flow: {r[0]}个交易日, {r[1]}只股票, {r[2]}条")
        print(f"   范围: {r[3]} ~ {r[4]}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='补全资金流数据')
    parser.add_argument('--workers', type=int, default=20, help='并行数')
    parser.add_argument('--max', type=int, default=None, help='限制股票数(测试用)')
    args = parser.parse_args()
    main(workers=args.workers, max_stocks=args.max)
