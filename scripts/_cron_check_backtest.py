import sqlite3
s = sqlite3.connect("file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro", uri=True)
rows = s.execute("SELECT signal_date, sb_ew, sb_win, top10_ew, created_at FROM fusion_3f_backtest ORDER BY signal_date DESC LIMIT 3").fetchall()
for r in rows:
    print(r)
mx = s.execute("SELECT MAX(REPLACE(date,'-','')) FROM fusion_3f_signals").fetchone()
print("latest signal date:", mx)
s.close()
