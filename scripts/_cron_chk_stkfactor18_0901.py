import duckdb, sqlite3, time, subprocess, os

c = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('stk_factor max:', c.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0])

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('new_factors latest:', sig.execute("SELECT trade_date, COUNT(*) FROM new_factors GROUP BY 1 ORDER BY 1 DESC LIMIT 1").fetchone())

# Is a stuck cron script still holding a write lock? Check for .lock files and processes
import glob
print('lock files:', glob.glob('/Users/zantao/.hermes/stockdb/*.lock') + glob.glob('/Users/zantao/.hermes/stockdb/**/*.wal', recursive=True)[:5])
ps = subprocess.run(['ps', 'aux'], capture_output=True, text=True).stdout
for ln in ps.splitlines():
    if 'backfill_stk_factor' in ln or 'signal_agent' in ln or 'fusion_3f_engine' in ln:
        print('PROC:', ln[:150])