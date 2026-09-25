import sqlite3
c = sqlite3.connect('state.db')
print('signal_history 20260804 条数:', c.execute("SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='20260804'").fetchone()[0])
print('watchlist 20260804 条数:', c.execute("SELECT COUNT(*) FROM watchlist WHERE REPLACE(scan_date,'-','')='20260804'").fetchone()[0])
print('signal_history 最新5日:', [r[0] for r in c.execute("SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1 DESC LIMIT 5")])
print('watchlist 最新3日:', [r[0] for r in c.execute("SELECT DISTINCT REPLACE(scan_date,'-','') FROM watchlist ORDER BY 1 DESC LIMIT 3")])
print('20260804 watchlist TOP3:', c.execute("SELECT ts_code, score FROM watchlist WHERE REPLACE(scan_date,'-','')='20260804' ORDER BY score DESC LIMIT 3").fetchall())
# 复制检测独立复核: 20260804 vs 20260803 同股票分数
rows1 = c.execute("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='20260804'").fetchall()
rows2 = c.execute("SELECT stock_code, reg10, reg20, reg40, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='20260803'").fetchall()
m2 = {r[0]: tuple(r[1:]) for r in rows2}
same = sum(1 for r in rows1 if r[0] in m2 and tuple(r[1:]) == m2[r[0]])
print(f'复制独立复核: 20260804共{len(rows1)}条, 与20260803完全相同 {same}条 ({same/max(len(rows1),1)*100:.2f}%)')
c.close()
