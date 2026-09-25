import json
orders = [
 {"action":"SELL","code":"605598","shares":100,"reason":"测试：部分卖出100股"},
]
json.dump(orders, open('/tmp/agent_orders_part_sell.json','w'), ensure_ascii=False)
import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=15)
print(c.execute("SELECT quantity FROM strategy_positions WHERE account_id='agent_auto' AND code='605598'").fetchall())
