#!/usr/bin/env /usr/bin/python3 -B
import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sd = "20260914"
top = c.execute("SELECT stock_code, stock_name, reg10 FROM signal_history WHERE REPLACE(date,'-','')=? ORDER BY reg10 DESC LIMIT 10", (sd,)).fetchall()
clf = {str(k): float(v) for k, v in c.execute("SELECT code, score FROM shadow_clf10_scores WHERE date=?", (sd,)).fetchall()}
for code, name, r in top:
    print(f"{code} {name}: reg10={float(r):.4f}  clf={clf.get(str(code),float('nan')):.4f}")
