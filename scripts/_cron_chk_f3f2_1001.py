import sqlite3
c = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
cols = [r[1] for r in c.execute("pragma table_info(fusion_3f_signals)").fetchall()]
print('cols:', cols)
dcol = 'trade_date' if 'trade_date' in cols else ('date' if 'date' in cols else cols[0])
print('max dates:', c.execute(f"select {dcol}, count(*) from fusion_3f_signals group by 1 order by 1 desc limit 5").fetchall())
