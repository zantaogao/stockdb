import sqlite3, os
base = os.path.expanduser('~/.hermes/stockdb')
c = sqlite3.connect(os.path.join(base, 'ledger.db'))
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
strat_tabs = [t for t in tabs if 'strateg' in t.lower() or 'nav' in t.lower()]
print('tables:', strat_tabs)
for t in strat_tabs:
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
    print(t, cols)
# trades today
for t in strat_tabs:
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
    dcol = next((x for x in ('trade_date','date','nav_date') if x in cols), None)
    if dcol:
        rows = c.execute(f"SELECT * FROM {t} WHERE {dcol} IN ('20260918','2026-09-18')").fetchall()
        print(f'-- {t} 0918 rows: {len(rows)}')
        for r in rows[:80]:
            print(r)
