#!/usr/bin/env python3
"""通宵补资金流 — 只补记录<100条的股票，慢速防封"""
import os, time, duckdb, random, sys
from datetime import datetime

DB = os.path.expanduser("~/.hermes/stockdb/stock.db")
BATCH_SIZE = 20  # 每批20只，中间休息
SLEEP_BETWEEN = 5  # 每只间隔5秒
SLEEP_BATCH = 120  # 每批休息2分钟

conn = duckdb.connect(DB)
# 找记录<100条的股票
need = conn.execute("""
    SELECT stock_code FROM stock_info si
    WHERE LEFT(stock_code, 3) != '920'
    AND stock_code NOT IN (
        SELECT stock_code FROM money_flow GROUP BY stock_code HAVING COUNT(*) >= 100
    )
    ORDER BY stock_code
""").fetchall()
conn.close()

codes = [r[0] for r in need]
total = len(codes)
print(f"需补资金流: {total}只")
print(f"预计{total*SLEEP_BETWEEN/3600:.1f}小时 ({total}只×{SLEEP_BETWEEN}s)")
print()

import akshare as ak

conn = duckdb.connect(DB)
done, fails, batch = 0, 0, 0

for i, code in enumerate(codes):
    prefix = 'sh' if code.startswith('6') else 'sz'
    try:
        time.sleep(random.uniform(SLEEP_BETWEEN - 1, SLEEP_BETWEEN + 2))
        df = ak.stock_individual_fund_flow(stock=code, market=prefix)
        
        if df is not None and len(df) > 0:
            records = []
            for _, row in df.iterrows():
                records.append((
                    code,
                    str(row['日期']),
                    float(row['主力净流入-净额']) if row['主力净流入-净额'] else 0,
                    float(row['小单净流入-净额']) if row['小单净流入-净额'] else 0,
                    round(float(row['主力净流入-净占比']) if row['主力净流入-净占比'] else 0, 2),
                ))
            
            conn.execute("BEGIN TRANSACTION")
            for r in records:
                conn.execute(
                    "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?, ?, ?, ?, ?)",
                    r
                )
            conn.execute("COMMIT")
            done += 1
            fails = 0
        else:
            fails += 1
    except Exception as e:
        fails += 1
        err = str(e)[:50]
        time.sleep(30)  # 出错多等一会儿
    
    batch += 1
    if batch % 10 == 0:
        elapsed = time.time() - t0 if 't0' in dir() else 0
        rate = batch / max(elapsed, 1) * 60
        count = conn.execute("SELECT COUNT(*) FROM money_flow").fetchone()[0]
        print(f"  {i+1}/{total} 已完成{done}只 失败{fails}次 总{count}条 速率{rate:.0f}只/分", flush=True)
    
    if fails >= 5:
        print(f"  ❌ 连续失败{fails}次，暂停5分钟...")
        time.sleep(300)
        fails = 0
    
    if batch >= BATCH_SIZE:
        print(f"  💤 批次完成，休息{SLEEP_BATCH//60}分钟...")
        time.sleep(SLEEP_BATCH)
        batch = 0

count = conn.execute("SELECT COUNT(*) FROM money_flow").fetchone()[0]
print(f"\n完成! 总记录: {count}条")
conn.close()
