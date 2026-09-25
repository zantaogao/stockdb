import duckdb, sqlite3, os, json, re
H = os.path.expanduser('~/.hermes/stockdb')
t = duckdb.connect(f'{H}/tushare.db', read_only=True)
c = sqlite3.connect(f'{H}/ledger.db')

print('== strategy_accounts_meta cols ==')
cols = [x[1] for x in c.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()]
print(cols)
for r in c.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    acc = r[0]
    cfg = None
    j = None
    for x in r:
        if isinstance(x, str) and x.strip().startswith('{'):
            try: j = json.loads(x)
            except: pass
    lrd = j.get('last_rebalance_date') if j else None
    if lrd:
        d = re.sub('-','',str(lrd))
        n = t.execute(f"SELECT COUNT(*) FROM daily WHERE trade_date > '{d}' AND trade_date <= '20260918'").fetchone()[0]
        print(f'{acc}: last_rebal={lrd} 已过{n}个交易日')
    else:
        print(acc, 'no lrd in', j if j else r[:4])

print('== holdings 全列 ==')
hcols = [x[1] for x in c.execute("PRAGMA table_info(holdings)").fetchall()]
print(hcols)
for r in c.execute("SELECT * FROM holdings").fetchall(): print('  ', r)

print('== watchlist ==')
wcols = [x[1] for x in c.execute("PRAGMA table_info(watchlist)").fetchall()]
print(wcols)
for r in c.execute("SELECT * FROM watchlist").fetchall(): print('  ', r)

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
