import subprocess, shutil, os, time

# 1) Which python does the cron-scheduled script actually get? (sys.executable of the
#    running scheduler + PATH of build_subprocess_env)
import subprocess as sp
ps = sp.run(['ps', 'aux'], capture_output=True, text=True).stdout
for ln in ps.splitlines():
    if ('gateway' in ln or 'hermes' in ln or 'cron' in ln) and 'grep' not in ln and 'Python.app' in ln:
        print('PROC:', ln[:200])

# 2) Does /usr/bin/python3 (CLI) have tushare?
r = sp.run(['/usr/bin/python3', '-c', 'import tushare, duckdb; print("CLI python: tushare", tushare.__version__)'],
           capture_output=True, text=True)
print('CLI python:', (r.stdout or r.stderr).strip()[:120])

# 3) current state of things
import sqlite3, duckdb
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
for t, c in [('new_factors', 'trade_date'), ('fusion_3f_signals', 'signal_date'), ('fusion_center_signals', 'trade_date')]:
    print(t, sig.execute(f'SELECT {c}, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 1').fetchone())
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('stk_factor:', d.execute('SELECT MAX(trade_date), COUNT(*) FROM stk_factor WHERE trade_date=(SELECT MAX(trade_date) FROM stk_factor)').fetchone())

# 4) is the stuck signal_agent still running?
r = sp.run(['ps', '-p', '30568', '-o', 'etime'], capture_output=True, text=True)
print('signal_agent 30568:', r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'GONE')