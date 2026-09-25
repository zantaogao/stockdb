#!/usr/bin/env python3
"""单测 exec_agent sync_to_db 的 trade_log UPSERT 语义（内存库，不碰真实 state.db）"""
import sqlite3

conn = sqlite3.connect(':memory:')
conn.execute("""CREATE TABLE trade_log (
    id INTEGER, code TEXT, name TEXT, direction TEXT, quantity INTEGER,
    price REAL, amount REAL, trade_date TEXT, trade_time TEXT, strategy TEXT, notes TEXT)""")

# 预置：当天主账户 2 条（1 条带时间、1 条空时间）+ 策略账户 1 条（带时间）
conn.execute("INSERT INTO trade_log VALUES (1,'600001','甲','BUY',100,10.0,1000.0,'2026-08-03','09:31:00',NULL,'auto_sync')")
conn.execute("INSERT INTO trade_log VALUES (2,'600002','乙','BUY',200,20.0,4000.0,'2026-08-03',NULL,NULL,'auto_sync')")
conn.execute("INSERT INTO trade_log VALUES (3,'300001','策略股','BUY',100,5.0,500.0,'2026-08-03','09:30:00','fusion3f','策略模拟账户')")

def sync(results, now_ts='13:12:00'):
    today = '2026-08-03'
    max_id = conn.execute("SELECT MAX(id) FROM trade_log WHERE trade_date = ? OR trade_date > ?", (today, today)).fetchone()[0] or 0
    existing_today = {}
    for row in conn.execute("SELECT code, direction, id FROM trade_log WHERE trade_date = ? AND (strategy IS NULL OR strategy = 'main')", (today,)).fetchall():
        existing_today[(row[0], row[1])] = row[2]
    new_id = max_id
    for r in results:
        if r.get('status') != 'EXECUTED':
            continue
        direction = 'BUY' if r.get('action') == 'BUY' else 'SELL'
        key = (r.get('stock_code'), direction)
        if key in existing_today:
            conn.execute("""UPDATE trade_log SET price=?, quantity=?, amount=?, trade_time=COALESCE(trade_time, ?) WHERE id=?""",
                         (r.get('price', 0), r.get('shares', 0), r.get('total_cost') or r.get('amount', 0), now_ts, existing_today[key]))
        else:
            new_id += 1
            conn.execute("""INSERT INTO trade_log (id, code, name, direction, quantity, price, amount, trade_date, trade_time, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'auto_sync')""",
                         (new_id, r.get('stock_code'), r.get('stock_name'), direction,
                          r.get('shares', 0), r.get('price', 0), r.get('total_cost') or r.get('amount', 0), today, now_ts))

# 场景：第二次运行，包含 600001(重复) / 600002(重复) / 600003(新)
sync([
    {'status': 'EXECUTED', 'action': 'BUY', 'stock_code': '600001', 'stock_name': '甲', 'shares': 150, 'price': 10.5, 'total_cost': 1575.0},
    {'status': 'EXECUTED', 'action': 'BUY', 'stock_code': '600002', 'stock_name': '乙', 'shares': 250, 'price': 20.5, 'total_cost': 5125.0},
    {'status': 'EXECUTED', 'action': 'BUY', 'stock_code': '600003', 'stock_name': '丙', 'shares': 300, 'price': 30.0, 'total_cost': 9000.0},
    {'status': 'FAILED', 'action': 'BUY', 'stock_code': '600099', 'stock_name': '失败单', 'shares': 100, 'price': 1.0, 'total_cost': 100.0},
])

rows = conn.execute("SELECT id, code, direction, quantity, price, trade_time, strategy, notes FROM trade_log ORDER BY id").fetchall()
print("id code     dir qty   price  time      strategy notes")
for r in rows:
    print(f"{r[0]}  {r[1]} {r[2]} {r[3]:>4} {r[4]:>6} {r[5] or 'NULL':<9} {r[6] or 'main':<9} {r[7]}")

assert len(rows) == 4, "应仍为 4 条（600001/600002 UPDATE，600003 新增，策略记录不动，失败单不插）"
r1 = conn.execute("SELECT * FROM trade_log WHERE id=1").fetchone()
assert r1[8] == '09:31:00', f"600001 首写时间应保留 09:31:00，实际 {r1[8]}"
assert r1[4] == 150 and r1[5] == 10.5, "600001 价格数量应更新"
r2 = conn.execute("SELECT * FROM trade_log WHERE id=2").fetchone()
assert r2[8] == '13:12:00', f"600002 空时间应被 COALESCE 补 now，实际 {r2[8]}"
r3 = conn.execute("SELECT * FROM trade_log WHERE id=4").fetchone()
assert r3[8] == '13:12:00', "600003 新插入应带时间"
r4 = conn.execute("SELECT * FROM trade_log WHERE id=3").fetchone()
assert r4[9] == 'fusion3f' and r4[8] == '09:30:00', "策略账户记录应原样保留"
print("\n✅ 全部断言通过：UPSERT 语义正确（保留首写时间/补空时间/新插带时间/策略记录不动/失败单不插）")
