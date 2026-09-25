#!/usr/bin/env python3
import duckdb, sqlite3, os, json
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
TU = duckdb.connect('tushare.db', read_only=True)
SG = sqlite3.connect('file:signals.db?mode=ro', uri=True)
LG = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
def sec(t): print('\n=====', t, '=====', flush=True)

sec('meta cols')
print([c[1] for c in LG.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()])
for r in LG.execute("SELECT * FROM strategy_accounts_meta").fetchall(): print(r)

sec('HOLDINGS')
print([c[1] for c in LG.execute("PRAGMA table_info(holdings)").fetchall()])
for r in LG.execute("SELECT * FROM holdings").fetchall(): print(r)

sec('WATCHLIST')
print([c[1] for c in LG.execute("PRAGMA table_info(watchlist)").fetchall()])
for r in LG.execute("SELECT * FROM watchlist").fetchall(): print(r)

sec('defense_state')
try:
    print([c[1] for c in LG.execute("PRAGMA table_info(defense_state)").fetchall()])
    for r in LG.execute("SELECT * FROM defense_state").fetchall(): print(r)
except Exception as e: print(e)

sec('today sector full ranking (d1)')
for r in TU.execute("""
SELECT b.industry, ROUND(AVG(d.pct_chg),2) chg, COUNT(*) n FROM daily d
JOIN stock_basic b ON d.ts_code=b.ts_code
WHERE d.trade_date='20260917' AND b.industry IS NOT NULL AND b.industry!=''
GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").fetchall(): print(r)
print('--- bottom ---')
for r in TU.execute("""
SELECT b.industry, ROUND(AVG(d.pct_chg),2) chg FROM daily d
JOIN stock_basic b ON d.ts_code=b.ts_code
WHERE d.trade_date='20260917' AND b.industry IS NOT NULL AND b.industry!=''
GROUP BY 1 ORDER BY 2 ASC LIMIT 10""").fetchall(): print(r)

sec('fusion_ic_daily')
try:
    print([c[1] for c in SG.execute("PRAGMA table_info(fusion_ic_daily)").fetchall()])
    for r in SG.execute("SELECT * FROM fusion_ic_daily ORDER BY 1 DESC LIMIT 12").fetchall(): print(r)
except Exception as e: print(e)

sec('center_dual_ic_daily')
try:
    print([c[1] for c in SG.execute("PRAGMA table_info(center_dual_ic_daily)").fetchall()])
    for r in SG.execute("SELECT * FROM center_dual_ic_daily ORDER BY 1 DESC LIMIT 12").fetchall(): print(r)
except Exception as e: print(e)

sec('ic_window')
try:
    print([c[1] for c in SG.execute("PRAGMA table_info(ic_window)").fetchall()])
    for r in SG.execute("SELECT * FROM ic_window ORDER BY 1 DESC LIMIT 20").fetchall(): print(r)
except Exception as e: print(e)

sec('strategy_accounts last rows')
for aid in ['fusion_center','center_dual','agent_auto','reg10_solo','cmmr','cmmr_fusion']:
    r=LG.execute("SELECT date,nav,daily_ret FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 3",(aid,)).fetchall()
    print(aid, r)

sec('CMMR ic last 10')
try:
    print([c[1] for c in SG.execute("PRAGMA table_info(cmmr_ic_daily)").fetchall()])
    for r in SG.execute("SELECT * FROM cmmr_ic_daily ORDER BY 1 DESC LIMIT 10").fetchall(): print(r)
except Exception as e: print(e)
print('\nDONE')
