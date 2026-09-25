import json
orders = [{"action":"SELL","code":"301338","reason":"测试：卖出边界"}]
json.dump(orders, open('/tmp/agent_orders_probe_sell.json','w'), ensure_ascii=False)
# 查询今日各策略已用额度
import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
print(c.execute("SELECT strategy, COUNT(*), SUM(CASE WHEN direction='BUY' THEN amount ELSE 0 END) FROM trade_log WHERE trade_date='2026-09-24' GROUP BY strategy").fetchall())
print('rowid max', c.execute("SELECT MAX(rowid) FROM trade_log").fetchall())
print('total rows today', c.execute("SELECT COUNT(*) FROM trade_log WHERE trade_date='2026-09-24'").fetchall())
