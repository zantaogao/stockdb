import sqlite3

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t in ['new_factors', 'fusion_3f_signals', 'fusion_center_signals']:
    cols = [r[1] for r in sig.execute(f'PRAGMA table_info({t})')]
    dcol = [c for c in cols if 'date' in c.lower()][0]
    print(t, 'latest:', sig.execute(f'SELECT {dcol}, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 1').fetchone())