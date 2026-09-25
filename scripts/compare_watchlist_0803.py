#!/usr/bin/env python3
"""对比 8/3 watchlist 新旧（重跑前后）"""
import sqlite3

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')          # 新
c2 = sqlite3.connect('/tmp/state.db.bak.20260803_235044_pre_rescan')  # 旧

def get_watchlist(conn, label):
    rows = conn.execute("SELECT ts_code, score, entry_low, entry_high, target_price, stop_loss FROM watchlist WHERE REPLACE(scan_date,'-','')='20260803' ORDER BY score DESC").fetchall()
    print(f'{label} watchlist {len(rows)} 行:')
    for r in rows:
        print(f'  {r[0]} score={r[1]:.0f} 下轨={r[2]} 上轨={r[3]} 目标={r[4]} 止损={r[5]}')
    return [r[0] for r in rows]

old = get_watchlist(c2, '旧(17:30 旧权重)')
print()
new = get_watchlist(c, '新(重跑 新权重)')

same = set(old) & set(new)
print(f'\n重合: {len(same)}/{len(old)}')
print(f'新进: {[x for x in new if x not in set(old)]}')
print(f'跌出: {[x for x in old if x not in set(new)]}')
