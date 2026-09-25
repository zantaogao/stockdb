import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db', timeout=30)
c.execute("ATTACH DATABASE '/Users/zantao/.hermes/stockdb/signals.db' AS sig")
codes = ('688659','003027','002875','300500','301276','300982','300908','603382','002942','002809','300556','301050','688681','603080')
q = "SELECT stock_code, stock_name, score FROM sig.fusion_center_signals WHERE REPLACE(date,'-','')='20260923' AND stock_code IN (%s) ORDER BY score DESC" % ','.join("'"+x+"'" for x in codes)
for r in c.execute(q).fetchall():
    print(r)
