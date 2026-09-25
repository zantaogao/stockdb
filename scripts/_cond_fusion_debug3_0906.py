#!/usr/bin/env python3
"""诊断：每个候选信号日 通过REPLACE查到的行数分布。"""
import sqlite3
st = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
rows = st.execute("""
  SELECT REPLACE(date,'-','') d, COUNT(*), 
         SUM(reg10 IS NOT NULL AND reg20 IS NOT NULL AND reg40 IS NOT NULL AND fusion_score IS NOT NULL)
  FROM signal_history GROUP BY d ORDER BY d
""").fetchall()
for d, n, ok in rows:
    print(d, n, ok)
st.close()