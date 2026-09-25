import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
rows = c.execute("SELECT date, stock_code, total_score FROM mean_reversion_signals WHERE REPLACE(date,'-','') = (SELECT MAX(REPLACE(date,'-','')) FROM mean_reversion_signals)").fetchall()
print('最新信号行数:', len(rows))
for r in rows:
    print(r)
c.close()
