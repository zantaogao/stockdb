import os, sqlite3
B = os.path.expanduser("~/.hermes/stockdb")
S = sqlite3.connect(f"file:{B}/signals.db", timeout=60)
print("rows:", S.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0])
print("distinct:", S.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_basic").fetchone()[0])
print("L上市(无后缀):", S.execute("SELECT COUNT(*) FROM stock_basic WHERE list_date NOT LIKE '%.D%' AND list_date NOT LIKE '%.P%'").fetchone()[0])
print("D退市:", S.execute("SELECT COUNT(*) FROM stock_basic WHERE list_date LIKE '%.D'").fetchone()[0])
print("市场分布:", S.execute("SELECT market, COUNT(*) FROM stock_basic GROUP BY market").fetchall())
# list_date 真实值采样
print("采样:", S.execute("SELECT stock_code,name,list_date FROM stock_basic ORDER BY stock_code LIMIT 3").fetchall())
miss = S.execute("SELECT COUNT(DISTINCT nf.stock_code) FROM new_factors nf WHERE nf.date='2026-09-24' AND nf.stock_code NOT IN (SELECT stock_code FROM fusion_3f_signals WHERE date='2026-09-24') AND nf.stock_code NOT IN (SELECT stock_code FROM stock_basic WHERE name LIKE '%ST%' OR name LIKE '%退%' OR market='北交所')").fetchone()[0]
print("0924有因子无fusion、非ST非北交(应0):", miss)
S.close()
