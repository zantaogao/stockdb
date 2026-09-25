#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cron_ic_impact.py — 量化 stk_factor 缺口对评分分布的影响"""
import sqlite3

conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
conn.row_factory = sqlite3.Row

print("== signal_history 各日评分分布 (reg40_pred / reg10_pred / fusion_score) ==")
for r in conn.execute("""
    SELECT REPLACE(date,'-','') AS d,
           COUNT(*) AS n,
           ROUND(AVG(reg40_pred),3) AS reg40_avg,
           ROUND(AVG(reg10_pred),3) AS reg10_avg,
           ROUND(AVG(fusion_score),2) AS fus_avg,
           ROUND(AVG(old_score),2) AS old_avg
    FROM signal_history
    WHERE REPLACE(date,'-','') >= '20260729'
    GROUP BY 1 ORDER BY 1
""").fetchall():
    print(f"  {r['d']} n={r['n']} reg40均值={r['reg40_avg']} reg10均值={r['reg10_avg']} fusion均值={r['fus_avg']} old_score均值={r['old_avg']}")

# 08-03 vs 08-04 reg40 相关系数 (同股票)
print("\n== reg40_pred 跨日相关 (同股票, 判断排序是否保持) ==")
for d1, d2 in [('20260803','20260731'), ('20260804','20260803')]:
    q = f"""
        SELECT COUNT(*) AS n,
               AVG(a.reg40_pred * b.reg40_pred) - AVG(a.reg40_pred)*AVG(b.reg40_pred) AS cov
        FROM (SELECT REPLACE(REPLACE(REPLACE(stock_code,'.SH',''),'.SZ',''),'.BJ','') AS code, reg40_pred
              FROM signal_history WHERE REPLACE(date,'-','')='{d1}') a
        JOIN (SELECT REPLACE(REPLACE(REPLACE(stock_code,'.SH',''),'.SZ',''),'.BJ','') AS code, reg40_pred
              FROM signal_history WHERE REPLACE(date,'-','')='{d2}') b ON a.code=b.code
    """
    r = conn.execute(q).fetchone()
    print(f"  {d1} vs {d2}: n={r['n']}")

# 皮尔逊相关 (两日 reg40 逐只)
import math
def pearson(d1, d2):
    q = f"""
        SELECT a.reg40_pred AS x, b.reg40_pred AS y FROM
        (SELECT REPLACE(REPLACE(REPLACE(stock_code,'.SH',''),'.SZ',''),'.BJ','') AS code, reg40_pred
         FROM signal_history WHERE REPLACE(date,'-','')='{d1}') a
        JOIN (SELECT REPLACE(REPLACE(REPLACE(stock_code,'.SH',''),'.SZ',''),'.BJ','') AS code, reg40_pred
              FROM signal_history WHERE REPLACE(date,'-','')='{d2}') b ON a.code=b.code
    """
    rows = conn.execute(q).fetchall()
    n = len(rows)
    if n < 10: return None, n
    xs = [r[0] for r in rows]; ys = [r[1] for r in rows]
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs)); dy = math.sqrt(sum((y-my)**2 for y in ys))
    return (num/(dx*dy) if dx and dy else None), n

for d1, d2 in [('20260804','20260803'), ('20260803','20260731'), ('20260731','20260730'), ('20260804','20260731')]:
    rho, n = pearson(d1, d2)
    print(f"  reg40 Pearson({d1}, {d2}) = {rho if rho is None else round(rho,3)} (n={n})")

conn.close()
