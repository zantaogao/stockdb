# -*- coding: utf-8 -*-
import duckdb, os
os.chdir('/Users/zantao/.hermes/stockdb')
c = duckdb.connect('tushare.db', read_only=True)
print('最新日期:', c.execute("SELECT MAX(date) FROM board_daily").fetchone())
print('board样例:', c.execute("SELECT DISTINCT board_code FROM board_daily WHERE date=(SELECT MAX(date) FROM board_daily) LIMIT 15").fetchall())
print('近8日行业板块（申万一级或同名分类）涨跌幅：')
rows = c.execute("""
SELECT board_code,
  MAX(CASE WHEN date='2026-09-21' THEN change_pct END) d21,
  MAX(CASE WHEN date='2026-09-18' THEN change_pct END) d18,
  MAX(CASE WHEN date='2026-09-17' THEN change_pct END) d17,
  MAX(CASE WHEN date='2026-09-16' THEN change_pct END) d16,
  MAX(CASE WHEN date='2026-09-15' THEN change_pct END) d15
FROM board_daily WHERE date>='2026-09-15' AND date<='2026-09-21'
GROUP BY board_code
""").fetchall()
import itertools
# 判断哪些是行业板块（跟draft领涨领跌对照）
named = [r for r in rows if r[1] is not None]
named.sort(key=lambda r: -r[1])
print('当日涨幅前12:', [(r[0], round(r[1],2)) for r in named[:12]])
print('当日涨幅后8:', [(r[0], round(r[1],2)) for r in named[-8:]])
print('5日累计前10（含每日值 d15,d16,d17,d18,d21）:')
named.sort(key=lambda r: sum(x for x in r[2:] if x is not None), reverse=True)
for r in named[:10]:
    print(r[0], '5日累计 %+.1f' % sum(x for x in r[2:] if x is not None), [None if x is None else round(x,2) for x in [r[4],r[3],r[2],r[5],r[1]]])
