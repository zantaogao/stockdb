import sqlite3, statistics
con=sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
rows=list(con.execute('select date,ic,win_rate,forward_days from cmmr_ic_daily order by date desc limit 6'))[::-1]
print('cmmr_ic_daily 近6行:')
for r in rows: print(r[0], 'IC', round(r[1],4), 'wr', round(r[2],3), 'fd', r[3])
rows=list(con.execute('select date,ic,win_rate,forward_days from fusion_ic_daily order by date desc limit 4'))[::-1]
print('fusion_ic_daily 近4行:')
for r in rows: print(r[0], 'IC', round(r[1],4), 'wr', round(r[2],3), 'fd', r[3])
