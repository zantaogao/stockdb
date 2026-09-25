# -*- coding: utf-8 -*-
import duckdb, os
os.chdir('/Users/zantao/.hermes/stockdb')
td = duckdb.connect('tushare.db', read_only=True)
for code, nm in [('000001.SH','上证'),('399001.SZ','深成'),('000852.SH','中证1000'),('000016.SH','上证50'),('399006.SZ','创业板')]:
    rows = td.execute("SELECT trade_date, close, pct_chg, vol FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 6", [code]).fetchall()
    print(nm, [(d[4:], round(c,1), round(p,2)) for d,c,p,v in reversed(rows)])
print('=== 涨跌家数近6日 ===')
for d,up,tot,amt in td.execute("""SELECT trade_date, SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END) up, COUNT(*) n, SUM(amount)/1e8 FROM daily WHERE trade_date>='20260914' GROUP BY 1 ORDER BY 1""").fetchall():
    print(d, '涨%d/%d=%.0f%% 额%.0f亿' % (up, tot, up/tot*100, amt))
