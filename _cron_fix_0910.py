import sqlite3, duckdb, json, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
print('status vals:', led.execute('SELECT DISTINCT status FROM holdings').fetchall())
print('==== main holdings (code like main?) ====')
tabs=[r[0] for r in led.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print(tabs)
# print all holdings with stop dist
for code,name,shares,cost,px,stop,tgt,st in led.execute("SELECT code,name,shares,avg_cost,latest_price,stop_loss,target_price,status FROM holdings").fetchall():
    ds = (px/stop-1)*100 if stop and px else None
    dt = (tgt/px-1)*100 if tgt and px else None
    print(st, code, name, 'px=%.2f'%px, 'dist_stop=%s'%('%.1f%%'%ds if ds is not None else '-'), 'dist_tgt=%s'%('%.1f%%'%dt if dt is not None else '-'))
print('==== meta ====')
try:
    cols=[r[1] for r in led.execute('PRAGMA table_info(strategy_accounts_meta)')]
    print(cols)
    for r in led.execute('SELECT * FROM strategy_accounts_meta').fetchall():
        print(r[0], str(r)[:300])
except Exception as e: print(e)
# 300779 check daily
tdb = duckdb.connect('tushare.db', read_only=True)
print(tdb.execute("SELECT MAX(trade_date), COUNT(*) FROM daily WHERE ts_code='300779.SH'").fetchall())
