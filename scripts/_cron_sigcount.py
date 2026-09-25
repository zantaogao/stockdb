#!/usr/bin/env python3
# _cron_sigcount 只读核对 signal_history 行数（health_verify 阈值排查）
import sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('file:signals.db?mode=ro', uri=True)
print('total,min,max:', c.execute("SELECT COUNT(*), MIN(REPLACE(date,'-','')), MAX(REPLACE(date,'-','')) FROM signal_history").fetchone())
print('top5 days:', c.execute("SELECT REPLACE(date,'-',''),COUNT(*) FROM signal_history GROUP BY 1 ORDER BY 2 DESC LIMIT 5").fetchall())
print('recent days:', c.execute("SELECT REPLACE(date,'-',''),COUNT(*) FROM signal_history WHERE date>='2026-09-01' OR date>='20260901' GROUP BY 1 ORDER BY 1 DESC LIMIT 15").fetchall())
# ic_daily latest
for t,col in [('ic_daily','signal_date'),('fusion_ic_daily','signal_date'),('center_dual_ic_daily','signal_date')]:
    try:
        print(t,'latest:', c.execute(f'SELECT MAX({col}) FROM {t}').fetchone())
    except Exception as e:
        print(t,'ERR',e)
