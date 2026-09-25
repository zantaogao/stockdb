import duckdb, sqlite3, json, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))

print('===== INDEX 5D =====')
tdb = duckdb.connect('tushare.db', read_only=True)
for ts in ['000852.SH','000001.SH']:
    try:
        rows = tdb.execute(f"SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 6").fetchall()
        print(ts, list(reversed(rows)))
    except Exception as e:
        print(ts, 'ERR', e)

print('===== LEDGER holdings stop dist =====')
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
led.row_factory = sqlite3.Row
cols = [r[1] for r in led.execute('PRAGMA table_info(holdings)')]
print('holdings cols:', cols)
rows = led.execute('SELECT * FROM holdings').fetchall()
for r in rows:
    d = dict(r)
    print({k: d.get(k) for k in ('stock_code','stock_name','qty','cost_price','current_price','stop_loss','target_price','take_profit','stop_price') if k in d})

print('===== strategy meta rebalance =====')
try:
    for r in led.execute("SELECT account_id, last_rebalance_date, config_json FROM strategy_accounts_meta").fetchall():
        print(r[0], r[1])
except Exception as e:
    print('ERR', e)

print('===== trading days forward =====')
d = tdb.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print('latest trade_date', d)

print('===== IC tables =====')
sig = sqlite3.connect('file:signals.db?mode=ro', uri=True)
sig.row_factory = sqlite3.Row
tabs = [r[0] for r in sig.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('tables:', tabs)
for t in ['ic_daily','fusion_ic_daily','cmmr_ic_daily','center_dual_ic_daily','ic_window','ic_shadow_442']:
    if t not in tabs:
        print(t, 'MISSING'); continue
    c = [x[1] for x in sig.execute(f'PRAGMA table_info({t})')]
    print('---', t, c)
    try:
        dcol = 'signal_date' if 'signal_date' in c else ('date' if 'date' in c else c[0])
        for r in sig.execute(f'SELECT * FROM {t} ORDER BY {dcol} DESC LIMIT 10').fetchall():
            print(dict(r))
    except Exception as e:
        print(t, 'ERR', e)
