#!/usr/bin/env python3
"""Check watchlist price ranges against backup DB"""
import sqlite3, duckdb, statistics, sys
from pathlib import Path
from collections import defaultdict

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = str(BASE / 'state.db')
LIVE_DB = str(BASE / 'tushare.db')

# Read watchlist
conn = sqlite3.connect(STATE_DB, timeout=10)
rows = conn.execute(
    "SELECT ts_code, score, scan_date, entry_low, entry_high, target_price, stop_loss "
    "FROM watchlist WHERE status='pending' ORDER BY score DESC"
).fetchall()
conn.close()

# Group by stock, keep latest scan_date only
by_stock = defaultdict(list)
for r in rows:
    date_str = str(r[2]).split(' ')[0] if r[2] else ''
    by_stock[r[0]].append({
        'code': r[0], 'score': r[1], 'scan_date': date_str,
        'entry_low': r[3], 'entry_high': r[4], 'target': r[5], 'stop': r[6]
    })

latest = {}
for code, entries in by_stock.items():
    entries.sort(key=lambda x: x['scan_date'], reverse=True)
    latest[code] = entries[0]

print(f"共 {len(latest)} 只唯一股票")

mismatches = []
checked = 0
for code, entry in sorted(latest.items(), key=lambda x: x[1]['score'], reverse=True):
    sd = entry['scan_date']
    if not sd:
        continue
    
    # Connect to backup DB
    try:
        bak = duckdb.connect(LIVE_DB, read_only=True)
        ts_code = f"{code}.SH" if code.startswith(('6','68','9')) else f"{code}.SZ"
        close_rows = bak.execute(
            f"SELECT close FROM daily WHERE ts_code='{ts_code}' AND trade_date <= '{sd.replace('-', '')}' ORDER BY trade_date DESC LIMIT 20"
        ).fetchall()
        bak.close()
    except Exception as e:
        print(f"  {code} DB error: {e}")
        continue
    
    if len(close_rows) < 20:
        print(f"  {code} 数据不足{len(close_rows)}天, 跳过")
        continue
    
    prices = [float(r[0]) for r in close_rows[::-1]]
    ma20 = statistics.mean(prices)
    std20 = statistics.stdev(prices)
    correct_el = round(ma20 - 2 * std20, 2)
    correct_eh = round(ma20 + 0.5 * std20, 2)
    correct_tg = round(ma20 + 2 * std20, 2)
    correct_sl = round(ma20 - 2 * std20, 2)
    
    watch_el = entry['entry_low']
    watch_eh = entry['entry_high']
    
    if watch_el <= 0:
        continue
    
    el_diff = abs(watch_el - correct_el) / correct_el * 100
    eh_diff = abs(watch_eh - correct_eh) / correct_eh * 100
    
    if el_diff > 10 or eh_diff > 10:
        mismatches.append({
            'code': code, 'date': sd, 'score': entry['score'],
            'w_el': watch_el, 'w_eh': watch_eh, 'w_tg': entry['target'], 'w_sl': entry['stop'],
            'c_el': correct_el, 'c_eh': correct_eh, 'c_tg': correct_tg, 'c_sl': correct_sl,
            'el_d': round(el_diff, 1), 'eh_d': round(eh_diff, 1)
        })
    
    checked += 1
    if checked % 10 == 0:
        print(f"  已检查 {checked}/{len(latest)}...")

print(f"\n\n=== 价格对不上的股票（偏离>10%）=== ")
print(f"{'代码':>8} {'日期':>10} {'评分':>6} {'原low':>8} {'正low':>8} {'原high':>8} {'正high':>8} {'low偏':>7} {'high偏':>7}")
print("-" * 80)
for m in sorted(mismatches, key=lambda x: x['score'], reverse=True):
    print(f"{m['code']:>8} {m['date']:>10} {m['score']:>6.0f} {m['w_el']:>8.2f} {m['c_el']:>8.2f} {m['w_eh']:>8.2f} {m['c_eh']:>8.2f} {m['el_d']:>6.1f}% {m['eh_d']:>6.1f}%")

print(f"\n共 {len(mismatches)}/{len(latest)} 只有问题")
if mismatches:
    print("\n修复命令:")
    print("=" * 80)
    for m in mismatches:
        print(f"UPDATE watchlist SET entry_low={m['c_el']}, entry_high={m['c_eh']}, target_price={m['c_tg']}, stop_loss={m['c_sl']} WHERE ts_code='{m['code']}' AND scan_date='{m['date']}';")
