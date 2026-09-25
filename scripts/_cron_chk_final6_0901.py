import subprocess, os, time, glob

# 1) exact command lines of interesting procs
r = subprocess.run(['ps', '-ax', '-ww', '-o', 'pid,lstart,etime,command'], capture_output=True, text=True)
for l in r.stdout.splitlines():
    if 'MacOS/Python' in l and ('signal' in l or 'stockdb' in l or 'tushare' in l or 'fusion' in l):
        print('PROC:', l[:300])

# 2) tushare.db modified in last 30 min? atomic swap happened?
st = os.stat('/Users/zantao/.hermes/stockdb/tushare.db')
print('tushare.db mtime:', time.strftime('%H:%M:%S', time.localtime(st.st_mtime)), 'size(G):', round(st.st_size/1e9, 1))
tmp = glob.glob('/Users/zantao/.hermes/stockdb/*temp*' if False else '/Users/zantao/.hermes/stockdb/*.tmp*')
print('tmp db files:', tmp)

# 3) today's stk_factor rows (verify the 22:00 backfill landed)
import duckdb
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('stk_factor 0901 rows:', d.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date='20260901'").fetchone()[0])
print('daily 0901 rows:', d.execute("SELECT COUNT(*) FROM daily WHERE trade_date='20260901'").fetchone()[0])

# 4) signal_history 0901 rows (the main-account signal source)
import sqlite3
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('signal_history 0901:', sig.execute("SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='20260901'").fetchone()[0])