#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cron_ic_impact2.py — 查 signal_history 规模 + 优化后的分布对比"""
import sqlite3, math

conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
conn.row_factory = sqlite3.Row

n = conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0]
idx = conn.execute("PRAGMA index_list(signal_history)").fetchall()
print(f"signal_history 总行数: {n}")
print(f"索引: {[i[1] for i in idx]}")

# 分布对比: 只取需要的日期 (先按 date 前缀过滤, 避免全表)
print("\n== 各日评分分布 ==")
for r in conn.execute("""
    SELECT REPLACE(date,'-','') AS d,
           COUNT(*) AS n,
           ROUND(AVG(reg40_pred),3) AS reg40_avg,
           ROUND(AVG(reg10_pred),3) AS reg10_avg,
           ROUND(AVG(fusion_score),2) AS fus_avg
    FROM signal_history
    WHERE date LIKE '2026-07%' OR date LIKE '2026-08%'
    GROUP BY 1 HAVING d >= '20260729'
    ORDER BY 1
""").fetchall():
    print(f"  {r['d']} n={r['n']} reg40={r['reg40_avg']} reg10={r['reg10_avg']} fusion={r['fus_avg']}")

# 皮尔逊: 用 Python 内存计算 (只取目标日期行)
def load_day(d):
    rows = conn.execute("""
        SELECT REPLACE(REPLACE(REPLACE(stock_code,'.SH',''),'.SZ',''),'.BJ','') AS code, reg40_pred
        FROM signal_history WHERE REPLACE(date,'-','') = ?
    """, (d,)).fetchall()
    return {r[0]: r[1] for r in rows}

print("\n== reg40_pred 跨日 Pearson ==")
days = {'20260730': load_day('20260730'), '20260731': load_day('20260731'),
        '20260803': load_day('20260803'), '20260804': load_day('20260804')}
pairs = [('20260731','20260730'), ('20260803','20260731'), ('20260804','20260803'), ('20260804','20260731')]
for d1, d2 in pairs:
    common = [(days[d1][c], days[d2][c]) for c in days[d1] if c in days[d2]]
    m = len(common)
    if m < 10:
        print(f"  {d1} vs {d2}: n={m} (不足)"); continue
    xs = [p[0] for p in common]; ys = [p[1] for p in common]
    mx, my = sum(xs)/m, sum(ys)/m
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs)); dy = math.sqrt(sum((y-my)**2 for y in ys))
    rho = num/(dx*dy) if dx and dy else None
    print(f"  reg40 Pearson({d1},{d2}) = {round(rho,3) if rho else rho} (n={m})")

conn.close()
