import sqlite3
db = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
# 今日(20260928)实时快照：各持仓票最新scan的涨跌
codes = ['001238','003027','300837','300881','300970','300982','301167','301276','603382','603409','688592','688659']
print('--- fusion_3f_intraday 20260928 ---')
for c in codes:
    r = db.execute("SELECT stock_code,scan_time,price,change_pct FROM fusion_3f_intraday WHERE stock_code=? AND date='20260928' ORDER BY scan_time DESC LIMIT 1",(c,)).fetchone()
    print(r)
print('--- latest date in intraday table ---')
print(db.execute("SELECT MAX(date), MAX(scan_time) FROM fusion_3f_intraday").fetchone())
print('--- 3d累计(最近3个交易日close) 688592 300881 ---')
db2 = None
