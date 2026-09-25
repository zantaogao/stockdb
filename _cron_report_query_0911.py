import duckdb, sqlite3, json, datetime

# ---- 1) 指数近5日 ----
t = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('== index_daily_raw 近5日 ==')
for ts in ('000852.SH','000001.SH'):
    rows = t.execute(f"SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE ts_code='{ts}' ORDER BY trade_date DESC LIMIT 5").fetchall()
    print(ts, list(reversed(rows)))

# ---- 2) 主账户持仓距止损/目标（ledger holdings/watchlist）----
led = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
led.row_factory = sqlite3.Row
print('\n== holdings columns ==')
cols = [r[1] for r in led.execute('PRAGMA table_info(holdings)')]
print(cols)
print('\n== holdings ==')
for r in led.execute('SELECT * FROM holdings').fetchall():
    print(dict(r))
print('\n== watchlist columns ==')
wcols = [r[1] for r in led.execute('PRAGMA table_info(watchlist)')]
print(wcols)

# ---- 3) 策略账户 last_rebalance_date + 剩余交易日 ----
print('\n== strategy_accounts_meta ==')
rows = led.execute('SELECT * FROM strategy_accounts_meta').fetchall()
mcols = [d[0] for d in led.execute('SELECT * FROM strategy_accounts_meta LIMIT 0').description]
print(mcols)
trade_dates = [r[0] for r in t.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date<='20260911' ORDER BY trade_date DESC LIMIT 60").fetchall()]
trade_dates = sorted(trade_dates)
def future_dates():
    # trading days after 20260911: estimate from daily history? use last known + weekday approximation
    return None
for r in rows:
    d = dict(zip(mcols, r))
    print(d)
    cfg = d.get('config_json')
    if cfg:
        try:
            c = json.loads(cfg)
            print('   config keys:', {k:c[k] for k in c if 'reb' in k.lower() or 'window' in k.lower() or 'date' in k.lower()})
        except Exception as e:
            print('   cfg parse err', e)
    lrd = d.get('last_rebalance_date')
    if lrd:
        lrd_c = lrd.replace('-','')
        # remaining trading days until window expires: need future calendar; count business days approx + actual past check
        print('   last_rebalance_date raw:', lrd)

# 交易日历：用 daily 表最近交易日确认 0911 是最新
print('\nlatest trade_date in daily:', t.execute('SELECT MAX(trade_date) FROM daily').fetchone()[0])
# 各窗口20/20账户：从 last_rebalance 起已过交易日数（0911当日收盘后，含当日与否按已过=该日之后至今的交易日）
def elapsed(lrd):
    l = lrd.replace('-','')
    return len([d for d in trade_dates if d > l])  # rebalance日之后到0911的交易日数
for r in rows:
    d = dict(zip(mcols, r))
    if d.get('last_rebalance_date'):
        print(d.get('account_id'), d.get('account_name'), 'elapsed_trading_days=', elapsed(d['last_rebalance_date']))

# ---- 4) 分模型 IC 近10日 ----
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
sig.row_factory = sqlite3.Row
print('\n== ic_daily 近12 ==')
for r in sig.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 12").fetchall():
    print(dict(r))
for tbl in ('fusion_ic_daily','center_dual_ic_daily','ic_window'):
    try:
        print(f'\n== {tbl} ==')
        cols = [x[1] for x in sig.execute(f'PRAGMA table_info({tbl})')]
        print('cols:', cols)
        order = 'signal_date' if 'signal_date' in cols else cols[0]
        for r in sig.execute(f'SELECT * FROM {tbl} ORDER BY {order} DESC LIMIT 12').fetchall():
            print(dict(r))
    except Exception as e:
        print(tbl, 'ERR', e)
