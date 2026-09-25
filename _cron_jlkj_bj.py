#!/usr/bin/env python3
"""本地统计近期北交所新股上市首日表现"""
import duckdb
conn = duckdb.connect('tushare.db', read_only=True)

# 2026年上市的北交所新股
rows = conn.execute("""
    SELECT ts_code, name, list_date FROM stock_basic
    WHERE market='北交所' AND list_date >= '20260601' ORDER BY list_date DESC
""").fetchall()

print(f"{'代码':<12}{'名称':<10}{'上市日':<10}{'首日涨跌%':>10}{'前5日累计%':>12}")
print('-' * 60)
for code, name, list_date in rows:
    # 首日 = 上市后第一个交易日（list_date 本身可能就是）
    d = conn.execute("""
        SELECT trade_date, pct_chg, close FROM daily
        WHERE ts_code=? AND trade_date >= ? ORDER BY trade_date LIMIT 6
    """, (code, str(list_date))).fetchall()
    if not d:
        print(f"{code:<12}{name:<10}{list_date:<10}  无数据")
        continue
    first = d[0]
    cum = 1.0
    for r in d:
        cum *= (1 + (r[1] or 0)/100)
    pct5 = (cum - 1) * 100
    print(f"{code:<12}{name:<10}{first[0]:<10}{first[1]:>10.1f}{pct5:>12.1f}")

# 北交所新股 2026 上半年整体首日表现
print("\n=== 2026年全部北交所新股首日涨跌统计 ===")
rows = conn.execute("""
    SELECT ts_code, name, list_date FROM stock_basic
    WHERE market='北交所' AND list_date >= '20260101' ORDER BY list_date
""").fetchall()
first_day = []
for code, name, list_date in rows:
    r = conn.execute("""
        SELECT pct_chg FROM daily WHERE ts_code=? AND trade_date >= ? ORDER BY trade_date LIMIT 1
    """, (code, str(list_date))).fetchone()
    if r and r[0] is not None:
        first_day.append((name, list_date, r[0]))
print(f"共 {len(first_day)} 只")
if first_day:
    pcts = [x[2] for x in first_day]
    pos = sum(1 for p in pcts if p > 0)
    neg = sum(1 for p in pcts if p < 0)
    avg = sum(pcts)/len(pcts)
    mx = max(first_day, key=lambda x: x[2])
    mn = min(first_day, key=lambda x: x[2])
    print(f"平均首日涨幅: {avg:.1f}%  上涨{pos}只/下跌{neg}只")
    print(f"最强: {mx[0]} {mx[1]} +{mx[2]:.1f}%")
    print(f"最弱: {mn[0]} {mn[1]} {mn[2]:.1f}%")
    print("\n明细:")
    for name, ld, p in first_day[-25:]:
        print(f"  {name:<10} {ld}  {p:+.1f}%")

conn.close()
