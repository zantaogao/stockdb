import duckdb, os
os.chdir('/Users/zantao/.hermes/stockdb')
con = duckdb.connect('tushare.db', read_only=True)
tabs=[r[0] for r in con.execute("SHOW TABLES").fetchall() if 'cal' in r[0].lower()]
print("cal tabs:", tabs)
if tabs:
    t=tabs[0]
    cols=[c[0] for c in con.execute(f"DESCRIBE {t}").fetchall()]
    print(t, cols)
    print("next trading days after 20260930:", con.execute(f"SELECT * FROM {t} WHERE {('trade_date' if 'trade_date' in cols else 'cal_date')}>'20260930' LIMIT 8").fetchall())
# 康欣新材 最近5日日线
print("康欣新材:", con.execute("SELECT trade_date,close,pct_chg FROM daily WHERE ts_code='600076.SH' ORDER BY trade_date DESC LIMIT 5").fetchall())
# 距止损口径: stop=2.18 close?
con.close()
