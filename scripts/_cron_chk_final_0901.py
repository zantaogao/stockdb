import sqlite3, duckdb, subprocess, datetime, time

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('new_factors cols:', [r[1] for r in sig.execute('PRAGMA table_info(new_factors)')][:8])
for t, c in [('new_factors', 'date'), ('fusion_3f_signals', 'signal_date'), ('fusion_center_signals', 'trade_date')]:
    try:
        print(t, sig.execute(f'SELECT {c}, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 1').fetchone())
    except Exception as e:
        print(t, 'ERR', str(e)[:60])

d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('stk_factor latest:', d.execute('SELECT MAX(trade_date) FROM stk_factor').fetchone()[0],
      d.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date=(SELECT MAX(trade_date) FROM stk_factor)").fetchone()[0], 'rows')

# signal_agent 30568 status
r = subprocess.run(['ps', '-p', '30568', '-o', 'etime,%cpu,state'], capture_output=True, text=True)
print('signal_agent 30568:', r.stdout.strip() or 'GONE')

# Is fusion_3f 08-31 present? And check tonight 09-01 signal presence everywhere
print('fusion_3f dates:', sig.execute("SELECT DISTINCT signal_date FROM fusion_3f_signals ORDER BY 1 DESC LIMIT 3").fetchall())
print('fusion_center dates:', sig.execute("SELECT DISTINCT trade_date FROM fusion_center_signals ORDER BY 1 DESC LIMIT 3").fetchall())