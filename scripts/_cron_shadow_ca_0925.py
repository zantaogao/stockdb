#!/usr/bin/env python3
# 0924 评分链路对除权票的实际处理：假跌票在 cur 列 vs adj 列的排名对照
import sqlite3
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db', timeout=10)
q = """
SELECT s.stock_code, c.ratio, c.fake_drop,
       s.fusion_cur, s.fusion_adj, s.pct_cur, s.pct_adj, s.is_ca, s.ca_gap
FROM signal_shadow s
JOIN ca_calendar c ON c.ts_code LIKE s.stock_code || '%' AND c.ex_date='20260923'
WHERE s.date='20260924'
ORDER BY s.pct_cur DESC
"""
rows = sig.execute(q).fetchall()
print(f'0923除权票在0924影子表: {len(rows)} 只')
print('code    ratio  fake跌  fusion现/复  pct现/复  gap')
for r in rows[:12]:
    print(f'{r[0]}  {r[1]:.3f}  {r[2]*100:5.1f}%  {str(r[3]):>7}/{str(r[4]):>7}  {str(r[5]):>7}/{str(r[6]):>7}  {r[8]}')
