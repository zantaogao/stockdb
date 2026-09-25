#!/usr/bin/env python3
"""现金恒等式核对 + 冷却表定位（只读）"""
import sqlite3, pathlib
SB = pathlib.Path.home() / '.hermes/stockdb'
led = sqlite3.connect(SB / 'ledger.db')
acts = {}
for r in led.execute("SELECT strategy,direction,SUM(amount) FROM trade_log WHERE REPLACE(trade_date,'-','')='20260914' GROUP BY 1,2"):
    acts.setdefault(r[0], {})[r[1]] = r[2]
print('=== 现金恒等式（今日现金变化 == 卖-买）===')
for a in ['cmmr', 'cmmr_fusion', 'fusion_center', 'center_dual', 'agent_auto']:
    prev = led.execute("SELECT cash FROM strategy_accounts WHERE account_id=? AND REPLACE(date,'-','')='20260911'", (a,)).fetchone()
    now = led.execute("SELECT cash FROM strategy_accounts WHERE account_id=? AND REPLACE(date,'-','')='20260914'", (a,)).fetchone()
    t = acts.get(a, {})
    delta = round(now[0] - prev[0], 2)
    expect = round(t.get('SELL', 0) - t.get('BUY', 0), 2)
    print(f'{a:12s} prev={prev[0]:>12,.2f} now={now[0]:>12,.2f} Δ={delta:>11,.2f} 期望={expect:>11,.2f} {"OK" if abs(delta-expect) < 1 else "MISMATCH"}')

print()
print('=== ledger.db 全部表 ===')
tabs = [r[0] for r in led.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print(tabs)
print()
print('=== 冷却/禁买相关表内容 ===')
for t in tabs:
    if any(k in t for k in ('cool', 'ban', 'stop')):
        cols = [c[1] for c in led.execute(f'PRAGMA table_info({t})')]
        rows = led.execute(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 6').fetchall()
        print(t, cols)
        for r in rows:
            print('   ', r)
