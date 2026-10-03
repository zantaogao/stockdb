# check fusion_3f_backtest latest date (signals.db at stockdb root)
import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
cur = con.cursor()
n, mn, mx = cur.execute("SELECT COUNT(*), MIN(signal_date), MAX(signal_date) FROM fusion_3f_backtest").fetchone()
print(f"rows={n} range={mn}..{mx}")
for r in cur.execute("SELECT signal_date, sb_ew, sb_win, mkt_ew FROM fusion_3f_backtest ORDER BY signal_date DESC LIMIT 3"):
    print(r)
