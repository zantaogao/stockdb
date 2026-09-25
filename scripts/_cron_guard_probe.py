import json, sqlite3
from datetime import datetime
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db', timeout=30)
c.execute("PRAGMA journal_mode=WAL")
rows = c.execute("SELECT trade_date, direction, code, quantity, amount FROM trade_log WHERE strategy='agent_auto' AND trade_date>='2026-09-15' ORDER BY trade_date").fetchall()
print('agent_auto 近期流水笔数:', len(rows))
orders = json.load(open('/tmp/agent_orders_probe.json'))
ts = datetime.now().strftime('%H:%M:%S')
for o in orders:
    if o['action'] == 'BUY':
        max_id = c.execute("SELECT MAX(id) FROM trade_log").fetchone()[0] or 0
        c.execute("INSERT INTO trade_log (id, code, name, direction, price, quantity, amount, trade_date, trade_time, strategy, signal_score, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (max_id + 1, o['code'], o.get('name',''), 'BUY', o['px'], o['shares'], round(o['px']*o['shares'],4), '2026-09-24', ts, 'agent_auto', None, f"[agent全权] {o['reason']}"))
        c.commit()
        print('inserted BUY', o['code'], o['shares'], '@', o['px'])
