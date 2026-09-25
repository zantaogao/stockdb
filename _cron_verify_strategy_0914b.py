#!/usr/bin/env python3
"""策略账户 20260914 一致性核对（只读，不写任何东西）"""
import sqlite3, pathlib, json

SB = pathlib.Path.home() / '.hermes/stockdb'
led = sqlite3.connect(SB / 'ledger.db')
led.row_factory = sqlite3.Row
d = '20260914'

print('=== strategy_accounts 今日行 (含重复检查) ===')
for r in led.execute("SELECT account_id,date,nav,cash,pos_value,daily_ret,market_ret,n_pos FROM strategy_accounts WHERE REPLACE(date,'-','')=? ORDER BY account_id", (d,)):
    print(dict(r))

print()
print('=== 重复行检查（同账户同日 >1 行）===')
print(led.execute("SELECT account_id, REPLACE(date,'-','') dd, COUNT(*) n FROM strategy_accounts GROUP BY account_id, dd HAVING n>1").fetchall())

print()
print('=== 昨日(20260911) NAV 参考 ===')
for r in led.execute("SELECT account_id, nav, n_pos FROM strategy_accounts WHERE REPLACE(date,'-','')='20260911'"):
    print(dict(r))

print()
print('=== 持仓非正股数 / 负现金检查 ===')
print('neg shares:', led.execute("SELECT account_id,code,shares FROM strategy_positions WHERE shares<=0").fetchall())
print('neg cash:', led.execute("SELECT account_id,cash FROM strategy_accounts_meta WHERE cash<0").fetchall())

print()
print('=== 今日成交流水（trade_log）与账户现金增减对账 ===')
rows = led.execute("SELECT strategy, direction, SUM(amount) FROM trade_log WHERE REPLACE(trade_date,'-','')=? GROUP BY strategy, direction ORDER BY strategy, direction", (d,)).fetchall()
for r in rows:
    print(tuple(r))

print()
print('=== JSON cash vs 表 cash ===')
for a in ['cmmr','cmmr_fusion','fusion_center','center_dual','agent_auto']:
    j = json.loads((SB/'sim_accounts'/f'{a}.json').read_text())
    t = led.execute("SELECT cash FROM strategy_accounts WHERE account_id=? AND REPLACE(date,'-','')=?", (a, d)).fetchone()
    print(f'{a:12s} json={j["cash"]:.2f} table={t[0] if t else None}')

print()
print('=== 冷却/止盈禁买表今日条目 ===')
for t in ['cooldown','tp_reentry_ban','sell_cooldown']:
    try:
        cols=[c[1] for c in led.execute(f'PRAGMA table_info({t})')]
        print(t, cols)
        for r in led.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 5"):
            print('   ', tuple(r))
    except Exception as e:
        print(t, 'ERR', e)
