# 核查：脚本写库的strategy表是否含今日NAV、是否有错误日志
import sqlite3, glob, os, time

# strategy_positions / meta freshness
con = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
cur = con.cursor()
for t in ['strategy_positions','strategy_accounts_meta','position_peaks','execution_logs']:
    cols=[c[1] for c in cur.execute(f'PRAGMA table_info({t})')]
    print(t, cols)
    try:
        for r in cur.execute(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 2'):
            print('  ', r)
    except Exception as e:
        print('  ERR', e)
con.close()

# any strategy script log written today
import subprocess
out = subprocess.run(['find','/Users/zantao/.hermes','/tmp','-maxdepth','4','-name','*strateg*','-newermt','2026-09-24 00:00'],
                     capture_output=True, text=True, timeout=30).stdout
print('--- files newer than today named *strateg* ---')
print(out[:2000])
