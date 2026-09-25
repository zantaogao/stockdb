import sqlite3
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
con = sqlite3.connect(str(BASE / 'ledger.db'))
con.row_factory = sqlite3.Row
print('=== trade_log 今日 2026-09-15 全部 ===')
rows = con.execute("SELECT * FROM trade_log WHERE trade_date='2026-09-15' ORDER BY trade_time").fetchall()
print('count:', len(rows))
for r in rows:
    d = dict(r)
    print('%s %-6s %-8s %-4s %8.2f x%-7s %10.1f | %-14s | %s' % (
        d['trade_time'], d['code'], (d['name'] or '')[:6], d['direction'], d['price'],
        d['quantity'], d['amount'] or 0, d['strategy'] or '', (d['notes'] or '')[:70]))
print('\n=== 按策略汇总 ===')
for r in con.execute("SELECT strategy, direction, COUNT(*) n, SUM(amount) amt FROM trade_log WHERE trade_date='2026-09-15' GROUP BY 1,2"):
    print(dict(r))
print('\n=== main 账户近5日成交 ===')
for r in con.execute("SELECT trade_date, trade_time, code, name, direction, price, quantity, notes FROM trade_log WHERE trade_date>='2026-09-09' AND (strategy IS NULL OR strategy NOT IN ('cmmr','cmmr_fusion','fusion_center','agent_auto','center_dual')) ORDER BY trade_time DESC LIMIT 25"):
    d = dict(r)
    print(d['trade_date'], d['trade_time'], d['code'], d['name'], d['direction'], d['price'], d['quantity'], '|', (d['notes'] or '')[:60])
print('\n=== holdings 明细(含buy_date) ===')
for r in con.execute("SELECT code, name, shares, avg_cost, buy_date, stop_loss, target_price, status FROM holdings ORDER BY buy_date"):
    print(dict(r))
print('\n=== position_peaks ===')
for r in con.execute("SELECT * FROM position_peaks"):
    print(dict(r))
con.close()
