import duckdb, sqlite3, os, json, re
H = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)
c = sqlite3.connect(f'{H}/ledger.db')

print('== 重评距今日数(distinct) ==')
mets = c.execute("SELECT account_id, config_json FROM strategy_accounts_meta").fetchall()
for acc, cj in mets:
    try: j = json.loads(cj)
    except: j = {}
    lrd = j.get('last_rebalance_date')
    if not lrd: print(acc,'no lrd'); continue
    d = re.sub('-','',str(lrd))
    n = t.execute(f"SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > '{d}' AND trade_date <= '20260918'").fetchone()[0]
    print(f'  {acc}: last_rebal={lrd} 已过{n}个交易日')

print('== watchlist 最新日 ==')
for r in c.execute("SELECT ts_code, score, scan_date, status, entry_low, entry_high, target_price, stop_loss, source FROM watchlist WHERE scan_date >= '20260915' OR scan_date >= '2026-09-15' ORDER BY scan_date DESC, score DESC LIMIT 20").fetchall():
    print('  W', r)

print('== signals.db IC ==')
s = sqlite3.connect(f'{H}/signals.db')
tabs = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print([x for x in tabs if 'ic' in x.lower()])
for tb in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','ic_window']:
    if tb not in tabs: print(tb,'MISSING'); continue
    cols = [x[1] for x in s.execute(f"PRAGMA table_info({tb})")]
    print(f'--- {tb}: {cols}')
    try:
        for r in s.execute(f"SELECT * FROM {tb} ORDER BY 1 DESC LIMIT 12").fetchall(): print('  ', r)
    except Exception as e: print('  err', e)
