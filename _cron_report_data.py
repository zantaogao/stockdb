import duckdb, sqlite3, json
# 1) index trend last 6 days
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print("== 指数近6日 ==")
for ts in ('000001.SH','000852.SH'):
    rows = con.execute("SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 6", [ts]).fetchall()
    print(ts, list(reversed(rows)))
# trading days since rebalance for each strategy account
print("== 重评日历 ==")
s = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
meta = s.execute("SELECT account_id, config_json FROM strategy_accounts_meta").fetchall()
tds = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260801' ORDER BY trade_date").fetchall()]
import datetime
for acc, cfg in meta:
    try:
        c = json.loads(cfg)
    except Exception:
        c = {}
    lb = c.get('last_rebalance_date') or c.get('last_rebalance') or c.get('rebalance_date')
    if lb:
        lb2 = lb.replace('-','')
        after = [d for d in tds if d > lb2]
        print(acc, 'last_rebalance=', lb, 'elapsed_td=', len(after))
    else:
        print(acc, 'no last_rebalance_date in config keys:', list(c.keys())[:8])
print("== 模型IC ic_daily 近10 ==")
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
cols = [r[1] for r in sig.execute("PRAGMA table_info(ic_daily)")]
print('ic_daily cols:', cols)
for r in sig.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall():
    print(r)
for t in ('fusion_ic_daily','cmmr_ic_daily','center_dual_ic_daily'):
    try:
        cols = [r[1] for r in sig.execute(f"PRAGMA table_info({t})")]
        print(f'== {t} cols:', cols)
        for r in sig.execute(f"SELECT * FROM {t} ORDER BY 1 DESC LIMIT 8").fetchall():
            print(r)
    except Exception as e:
        print(t, 'ERR', e)
print("== ic_window 近10 ==")
try:
    cols = [r[1] for r in sig.execute("PRAGMA table_info(ic_window)")]
    print('cols:', cols)
    for r in sig.execute("SELECT * FROM ic_window ORDER BY 1 DESC LIMIT 12").fetchall():
        print(r)
except Exception as e:
    print('ic_window ERR', e)