import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
cur = con.cursor()
print('--- fusion_3f_signals last dates ---')
for d, c in cur.execute("SELECT date, COUNT(*) FROM fusion_3f_signals GROUP BY date ORDER BY date DESC LIMIT 6"):
    print(d, c)
print('--- signal_history last dates ---')
for d, c in cur.execute("SELECT REPLACE(date,'-','') d2, COUNT(*) FROM signal_history GROUP BY d2 ORDER BY d2 DESC LIMIT 4"):
    print(d, c)
print('--- new_factors last dates ---')
try:
    for d, c in cur.execute("SELECT REPLACE(date,'-','') d2, COUNT(*) FROM new_factors GROUP BY d2 ORDER BY d2 DESC LIMIT 4"):
        print(d, c)
except Exception as e:
    print('new_factors:', e)