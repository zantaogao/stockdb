#!/usr/bin/env python3
# MacBook 侧：adj_factor 补丁存活 + daily 更新状态（正常输出以 OK 开头）
import duckdb
try:
    c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
    pre = c.execute("SELECT COUNT(*) FROM adj_factor WHERE trade_date < '20150101'").fetchone()[0]
    mn = c.execute("SELECT MIN(trade_date) FROM adj_factor").fetchone()[0]
    mx = c.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    c.close()
    bad = []
    if pre < 3_000_000:
        bad.append(f"adj_factor 2015 前只剩 {pre:,} 行（补丁被清）")
    if str(mn) > '20090105':
        bad.append(f"adj_factor 最早日={mn}")
    if str(mx) < '20260921':
        bad.append(f"daily 未更到 20260921（当前 {mx}）")
    print("FAIL " + "；".join(bad) if bad else f"OK adj_factor 2015前 {pre:,} 行 | 最早 {mn} | daily 最新 {mx}")
except Exception as e:
    print(f"FAIL 读取异常: {type(e).__name__}: {e}")
