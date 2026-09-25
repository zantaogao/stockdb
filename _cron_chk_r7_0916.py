import sqlite3, duckdb
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
px = {}
for code, close in con.execute("SELECT ts_code, close FROM daily WHERE trade_date='20260915'").fetchall():
    px[code.split('.')[0]] = close
sold = set()
for a, cd in c.execute("SELECT strategy, code FROM trade_log WHERE REPLACE(trade_date,'-','')='20260916' AND direction='SELL'"):
    sold.add((a, cd))
print("=== 各账户持仓 0915 收盘价口径浮亏检查（R7 线 -6%）===")
for a, code, name, sh, ac in c.execute("SELECT account_id,code,name,shares,avg_cost FROM strategy_positions ORDER BY account_id,code"):
    p = px.get(code)
    if p is None:
        print(f"{a:12s} {code} {name:6s} 无0915价")
        continue
    pnl = (p / ac - 1) * 100
    mark = " <== R7破线" if pnl <= -6 else ""
    mark += " [今日已卖]" if (a, code) in sold else ""
    if pnl <= -4:
        print(f"{a:12s} {code} {name:6s} {sh:>6} cost={ac:8.2f} px={p:8.2f} pnl={pnl:+6.2f}%{mark}")
print("=== 摘要：破线票数 ===")
n = 0
for a, code, name, sh, ac in c.execute("SELECT account_id,code,name,shares,avg_cost FROM strategy_positions"):
    p = px.get(code)
    if p is None:
        continue
    if (p / ac - 1) * 100 <= -6:
        n += 1
        print("R7破线未卖:", a, code, name, round((p / ac - 1) * 100, 2))
print("合计破线:", n)
