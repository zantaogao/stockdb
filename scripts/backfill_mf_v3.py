#!/usr/bin/env python3
"""
资金流补全 v3 — 1路慢速跑通宵，带指数退避
"""
import os, time, duckdb, random
import pandas as pd

DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def fetch_one(code, prefix, attempt=1):
    import akshare as ak
    try:
        time.sleep(random.uniform(2, 4))
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
        if attempt < 3:
            wait = 10 * attempt
            print(f"  ⚠️ {code} 失败({e}), {wait}s后重试({attempt}/3)...")
            time.sleep(wait)
            return fetch_one(code, prefix, attempt + 1)
        return []

def main():
    conn = duckdb.connect(DB)
    stocks = conn.execute("""
        SELECT stock_code FROM stock_info 
        WHERE LEFT(stock_code, 3) != '920'
        ORDER BY stock_code
    """).fetchall()
    have_data = set()
    for row in conn.execute("""
        SELECT stock_code FROM money_flow 
        WHERE date >= '2025-11-01' 
        GROUP BY stock_code HAVING COUNT(*) > 100
    """).fetchall():
        have_data.add(row[0])
    conn.close()
    
    todo = [s[0] for s in stocks if s[0] not in have_data]
    total = len(todo)
    print(f"需拉取: {total}只 (已跳过{len(have_data)}只完备的)")
    print(f"1路慢速, 每只~5-10秒, 预计{total*7/3600:.1f}小时\n")
    
    t0 = time.time()
    all_records = []
    fails = 0
    
    for i, code in enumerate(todo):
        prefix = 'sh' if code.startswith('6') else 'sz'
        records = fetch_one(code, prefix)
        
        if records:
            all_records.extend(records)
            fails = 0
        else:
            fails += 1
        
        if (i+1) % 100 == 0 or fails >= 10:
            elapsed = time.time() - t0
            rate = (i+1) / elapsed * 60
            print(f"  {i+1}/{total} ({i+1/total*100:.0f}%), {len(all_records)}条, {rate:.0f}只/分", flush=True)
            
            # 每100只写入一次
            if all_records:
                write_batch(all_records)
                all_records = []
            
            if fails >= 10:
                print(f"  ❌ 连续{fails}次失败，暂停30分钟...")
                time.sleep(1800)
                fails = 0
    
    # 最后写入
    if all_records:
        write_batch(all_records)
    
    elapsed = time.time() - t0
    print(f"\n完成! 耗时{elapsed/3600:.1f}小时")

def write_batch(records):
    conn = duckdb.connect(DB)
    try:
        conn.execute("BEGIN TRANSACTION")
        for r in records:
            conn.execute(
                "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?, ?, ?, ?, ?)",
                r
            )
        conn.execute("COMMIT")
        r2 = conn.execute("""
            SELECT COUNT(DISTINCT date), COUNT(DISTINCT stock_code), COUNT(*),
                   MIN(date), MAX(date) FROM money_flow
        """).fetchone()
        print(f"  ✅ 已写入, 当前: {r2[0]}交易日, {r2[1]}股票, {r2[2]}条, {r2[3]}~{r2[4]}")
    except Exception as e:
        conn.execute("ROLLBACK")
        print(f"  ❌ 写入失败: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    main()
