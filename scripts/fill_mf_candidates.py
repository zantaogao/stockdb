#!/usr/bin/env python3
"""补全指定股票的资金流数据"""
import os, time, duckdb, random, sys
from datetime import datetime, timedelta

DB = os.path.expanduser("~/.hermes/stockdb/stock.db")
codes = sys.argv[1:] if len(sys.argv) > 1 else []

if not codes:
    # 默认补候选池缺数据的股票
    conn = duckdb.connect(DB)
    codes = [r[0] for r in conn.execute("""
        SELECT m.stock_code FROM (
            SELECT stock_code, COUNT(*) as cnt FROM money_flow GROUP BY stock_code
        ) m WHERE m.cnt < 100 ORDER BY m.cnt ASC LIMIT 50
    """).fetchall()]
    conn.close()

print(f"需补资金流: {len(codes)}只")
print()

import akshare as ak

conn = duckdb.connect(DB)
total = len(codes)
done = 0

for code in codes:
    prefix = 'sh' if code.startswith('6') else 'sz'
    try:
        time.sleep(random.uniform(2, 4))
        df = ak.stock_individual_fund_flow(stock=code, market=prefix)
        if df is None or len(df) == 0:
            print(f"  {done+1}/{total} {code} 无数据")
            done += 1
            continue
        
        records = []
        for _, row in df.iterrows():
            records.append((
                code,
                str(row['日期']),
                float(row['主力净流入-净额']) if row['主力净流入-净额'] else 0,
                float(row['小单净流入-净额']) if row['小单净流入-净额'] else 0,
                round(float(row['主力净流入-净占比']) if row['主力净流入-净占比'] else 0, 2),
            ))
        
        # 写入
        conn.execute("BEGIN TRANSACTION")
        for r in records:
            conn.execute(
                "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?, ?, ?, ?, ?)",
                r
            )
        conn.execute("COMMIT")
        
        print(f"  ✅ {done+1}/{total} {code}: {len(records)}条 ({records[0][1]}~{records[-1][1]})")
        done += 1
    except Exception as e:
        print(f"  ⚠️ {done+1}/{total} {code}: {str(e)[:60]}")
        time.sleep(10)
        done += 1

conn.close()
print(f"\n完成! 补了{done}只")
