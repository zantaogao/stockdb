import json, os, sqlite3, datetime
base = os.path.expanduser('~/.hermes/stockdb')
sim = os.path.join(base, 'sim_accounts')
today = '20260914'
ACTIVE = ['cmmr', 'cmmr_fusion', 'fusion_center', 'center_dual', 'agent_auto']
CLOSED = ['fusion3f', 'fusion_dual']

c = sqlite3.connect(os.path.join(base, 'ledger.db'))
c.row_factory = sqlite3.Row
view_names = [r[0] for r in c.execute("SELECT name,type FROM sqlite_master WHERE type IN ('view','table') ORDER BY type,name")]
print('views/tables:', view_names)

print('\n=== per-account integrity ===')
for aid in ACTIVE + CLOSED:
    p = os.path.join(sim, aid + '.json')
    d = json.load(open(p))
    pos = d.get('positions', [])
    cash = d.get('cash')
    pv = sum(float(x.get('shares', 0)) * float(x.get('last_price') or x.get('current_price') or x.get('price') or 0) for x in pos)
    nav = d.get('nav') or d.get('total_value')
    navs = d.get('nav_history', [])
    keys = [str(h.get('date', '')).replace('-', '') for h in navs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    dbrows = c.execute("SELECT COUNT(*) FROM strategy_positions WHERE account_id=?", (aid,)).fetchone()[0]
    dbcash = c.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id=?", (aid,)).fetchone()
    print(f"{aid:14s} closed={bool(d.get('closed'))} cash={cash} posN={len(pos)} pos_val={pv:.0f} nav={nav} "
          f"last_nav_date={keys[-1] if keys else None} dup_dates={dup} db_pos={dbrows} db_cash={dbcash[0] if dbcash else None} "
          f"json_keys={sorted(d.keys())}" if not False else '')
    # mismatch flags
    flags = []
    if nav is not None and cash is not None:
        if abs((cash + pv) - float(nav)) > 1.0:
            flags.append(f'NAV_MISMATCH diff={cash+pv-float(nav):.1f}')
    if len(pos) != dbrows:
        flags.append(f'POS_COUNT_DIFF json={len(pos)} db={dbrows}')
    if dbcash and abs(float(dbcash[0]) - float(cash)) > 0.01:
        flags.append(f'CASH_DIFF json={cash} db={dbcash[0]}')
    if dup:
        flags.append('DUP_NAV_DATES ' + ','.join(dup))
    if keys and keys[-1] != today and aid not in CLOSED:
        flags.append(f'STALE_NAV last={keys[-1]}')
    print('   FLAGS:', flags if flags else 'OK')

print('\n=== trade_log today (all strategies) ===')
for r in c.execute("SELECT id,code,name,direction,price,quantity,trade_time,strategy FROM trade_log WHERE REPLACE(trade_date,'-','')=? ORDER BY id", (today,)):
    print(tuple(r))

print('\n=== ledger strategy view if present ===')
for t in ['strategy_accounts']:
    try:
        for r in c.execute(f"SELECT * FROM {t} LIMIT 12"):
            print(dict(r))
    except Exception as e:
        print(t, 'ERR', e)
