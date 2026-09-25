"""本轮tick独立核查 v2: 先看 DD 再查。只读。"""
import sqlite3, os

SD = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(SD, 'ledger.db'))
c.row_factory = sqlite3.Row

tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('tables:', tabs)
for t in tabs:
    if 'strategy' in t.lower():
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: n={n} cols={cols}")

for t in tabs:
    if 'strategy' in t.lower() and 'meta' not in t.lower():
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
        dcol = [x for x in cols if 'date' in x.lower()]
        print(f"\n=== {t} date-like cols: {dcol} ===")
        if dcol:
            q = f"SELECT account_id, {dcol[0]} d, COUNT(*) n FROM {t} GROUP BY account_id ORDER BY d DESC LIMIT 40"
            try:
                for r in c.execute(q):
                    print(dict(r))
            except Exception as e:
                print('ERR', e)
