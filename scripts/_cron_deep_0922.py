#!/usr/bin/env python3
# 0922 盘后深复盘取数（只读）
import duckdb, sqlite3, json, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))

def sec(t): print('\n===== '+t+' =====')

tdb = duckdb.connect('tushare.db', read_only=True)
sig = sqlite3.connect('signals.db')
led = sqlite3.connect('ledger.db')

sec('指数近8日 中证1000/上证/上证50/创业板 收盘+涨跌幅+成交额')
q = """SELECT ts_code, trade_date, close, pct_chg, vol*1000 vol_est FROM index_daily_raw
WHERE ts_code IN ('000852.SH','000001.SH','000016.SH','399006.SZ') AND trade_date>='20260910'
ORDER BY ts_code, trade_date"""
try:
    for r in tdb.execute(q).fetchall(): print(r)
except Exception as e:
    # fallback without vol
    for r in tdb.execute(q.replace(', vol*1000 vol_est','')).fetchall(): print(r)

sec('成交额对比: 修复日vs前一日 (全市场amount)')
try:
    for r in tdb.execute("""SELECT trade_date, SUM(amount)/1e8 amt_yi, COUNT(*) FILTER (WHERE pct_chg>0) upn,
COUNT(*) FILTER (WHERE pct_chg<0) down FROM daily_raw WHERE trade_date>='20260914' GROUP BY 1 ORDER BY 1""").fetchall(): print(r)
except Exception as e:
    print('daily_raw err', e)
    for r in tdb.execute("""SELECT trade_date, SUM(amount)/1e8 amt_yi FROM daily WHERE trade_date>='20260914' GROUP BY 1 ORDER BY 1""").fetchall(): print(r)

sec('行业板块近10日每日涨跌幅(申万) 前20强+持仓相关')
try:
    rows = tdb.execute("""
    SELECT d.trade_date, b.industry_name, d.pct_chg
    FROM sw_daily_raw d JOIN stock_industry_raw b ON d.ts_code=b.ts_code
    WHERE d.trade_date>='20260908'
    ORDER BY d.trade_date, d.pct_chg DESC""").fetchall()
    # pivot in python
    from collections import defaultdict
    days = sorted(set(r[0] for r in rows))
    ind = defaultdict(dict)
    for d,i,p in rows: ind[i][d]=p
    # 5-day cum & streak
    stats=[]
    for i,m in ind.items():
        cum5=0; n=0; streak=0
        for d in days[-5:]:
            if d in m: cum5+=m[d]; n+=1
        for d in reversed(days):
            if d in m and m[d]>0: streak+=1
            elif d in m: break
        stats.append((round(cum5,2), streak, i, [round(m.get(d,0),2) for d in days[-6:]]))
    stats.sort(reverse=True)
    for s in stats[:15]: print(s)
    print('--- 弱势 ---')
    for s in stats[-8:]: print(s)
except Exception as e:
    print('sw err', e)

sec('主账户持仓+止损止盈距离')
cols = [c[1] for c in led.execute("PRAGMA table_info(holdings)").fetchall()]
print('holdings cols:', cols)
for r in led.execute("SELECT * FROM holdings").fetchall(): print(r)
try:
    wlcols=[c[1] for c in led.execute("PRAGMA table_info(watchlist)").fetchall()]
    print('watchlist cols:', wlcols)
    for r in led.execute("SELECT * FROM watchlist ORDER BY rowid DESC LIMIT 20").fetchall(): print(r)
except Exception as e: print('wl err', e)

sec('策略账户 meta')
for r in led.execute("SELECT account_id, last_rebalance_date, config_json FROM strategy_accounts_meta").fetchall():
    print(r[0], r[1], (r[2] or '')[:120])

sec('重评剩余实交易日数核算')
# days since each last_rebalance
for acc,d0 in led.execute("SELECT account_id,last_rebalance_date FROM strategy_accounts_meta").fetchall():
    if not d0: print(acc,'None'); continue
    d = d0.replace('-','')
    n = tdb.execute("SELECT COUNT(*) FROM daily WHERE trade_date>? AND trade_date<='20260922'",[d]).fetchone()[0]
    print(acc, 'lastreb', d0, 'elapsed_trading_days', n)

sec('分模型IC近12信号日')
for t in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','ic_window']:
    try:
        cols=[c[1] for c in sig.execute(f"PRAGMA table_info({t})").fetchall()]
        print('--',t,cols)
        for r in sig.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 12").fetchall(): print(r)
    except Exception as e: print(t,'err',e)

sec('factor_ic_roll 最新')
try:
    cols=[c[1] for c in sig.execute("PRAGMA table_info(factor_ic_roll)").fetchall()]
    print(cols)
    for r in sig.execute("SELECT * FROM factor_ic_roll ORDER BY rowid DESC LIMIT 10").fetchall(): print(r)
except Exception as e: print('fir err',e)

print('\nDONE')
