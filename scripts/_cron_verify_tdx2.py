#!/usr/bin/env python3
import sqlite3, os
base = os.path.expanduser("~/.hermes/stockdb")
c = sqlite3.connect(os.path.join(base, "signals.db"))
for t in ["tdx_intraday_feat", "tdx_signal_log"]:
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
    print(t, cols)
    dcol = "date" if "date" in cols else cols[0]
    print("  recent:", c.execute(
        f"SELECT {dcol}, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 4").fetchall())
c.close()
