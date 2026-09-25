#!/usr/bin/env python3
"""验证 exec_agent peak 重置逻辑（内存库，不碰真实 state.db）"""
import sqlite3

conn = sqlite3.connect(':memory:')
conn.execute('CREATE TABLE position_peaks (code TEXT PRIMARY KEY, peak_price REAL, updated_at TEXT)')


def sync_peak(code, buy_date, latest_price, avg_cost, today, old_peaks):
    now = '2026-08-07T14:00:00'
    old_peak = old_peaks.get(code) or 0
    if (buy_date or '')[:10] == today:
        new_peak = max(latest_price, avg_cost)
        conn.execute('''
            INSERT INTO position_peaks (code, peak_price, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET peak_price = excluded.peak_price, updated_at = excluded.updated_at
        ''', (code, new_peak, now))
    else:
        new_peak = max(old_peak, latest_price, avg_cost)
        conn.execute('''
            INSERT INTO position_peaks (code, peak_price, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET peak_price = MAX(position_peaks.peak_price, ?), updated_at = ?
        ''', (code, new_peak, now, latest_price, now))
    return new_peak


def check(name, cond, detail):
    print(f'  {name}: {detail}  → {"✅" if cond else "❌失败"}')


# 场景1: 旧仓9.0峰 → 今天重新买入(成本8.2)
conn.execute("INSERT INTO position_peaks VALUES ('600508', 9.0, '2026-08-05')")
old = {'600508': 9.0}
new_peak = sync_peak('600508', '2026-08-07', 8.5, 8.2, '2026-08-07', old)
db_peak = conn.execute("SELECT peak_price FROM position_peaks WHERE code='600508'").fetchone()[0]
check('场景1 重新买入重置旧峰', db_peak < 9.0 and db_peak == 8.5, f'new_peak={new_peak} DB={db_peak} (旧峰9.0应被清)')

# 场景2: 加仓(昨天买入今天加) 保留旧峰
conn.execute('DELETE FROM position_peaks')
conn.execute("INSERT INTO position_peaks VALUES ('300649', 24.87, '2026-08-06')")
old = {'300649': 24.87}
new_peak = sync_peak('300649', '2026-08-06', 24.5, 20.0, '2026-08-07', old)
db_peak = conn.execute("SELECT peak_price FROM position_peaks WHERE code='300649'").fetchone()[0]
check('场景2 加仓保留旧峰', db_peak == 24.87, f'new_peak={new_peak} DB={db_peak} (旧峰24.87应保留)')

# 场景3: 普通持仓(非今日买入) peak 累积新高
conn.execute('DELETE FROM position_peaks')
conn.execute("INSERT INTO position_peaks VALUES ('600963', 3.43, '2026-08-06')")
old = {'600963': 3.43}
new_peak = sync_peak('600963', '2026-08-01', 3.5, 3.13, '2026-08-07', old)
db_peak = conn.execute("SELECT peak_price FROM position_peaks WHERE code='600963'").fetchone()[0]
check('场景3 非今日仓累积新高', db_peak == 3.5, f'new_peak={new_peak} DB={db_peak} (应累积到3.5)')

# 场景4: 全新首仓(peaks无记录)
conn.execute('DELETE FROM position_peaks')
old = {}
new_peak = sync_peak('301172', '2026-08-07', 17.8, 17.55, '2026-08-07', old)
db_peak = conn.execute("SELECT peak_price FROM position_peaks WHERE code='301172'").fetchone()[0]
check('场景4 全新首仓初始峰', db_peak == 17.8, f'new_peak={new_peak} DB={db_peak} (初始峰=现价17.8)')

# 场景5: 今日买入但收盘价低于成本（买入后下跌）
conn.execute('DELETE FROM position_peaks')
old = {'688168': 40.0}  # 模拟该 code 旧仓曾到 40（8/6 已卖）
new_peak = sync_peak('688168', '2026-08-07', 35.2, 35.47, '2026-08-07', old)
db_peak = conn.execute("SELECT peak_price FROM position_peaks WHERE code='688168'").fetchone()[0]
check('场景5 重新买入后下跌', db_peak == 35.47, f'new_peak={new_peak} DB={db_peak} (应=成本35.47, 旧峰40不残留)')

conn.close()
print('\n全部场景验证完毕')
