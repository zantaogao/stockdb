# -*- coding: utf-8 -*-
import duckdb, sqlite3, json, os
os.chdir('/Users/zantao/.hermes/stockdb')
sc = sqlite3.connect('signals.db')

print('===== IC 表结构与近12行 =====')
for t in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','cmmr_ic_daily','cmmr_top10_ic_daily','ic_window']:
    cols = [c[1] for c in sc.execute(f"PRAGMA table_info({t})").fetchall()]
    print('--', t, cols)
    dcol = 'signal_date' if 'signal_date' in cols else cols[0]
    try:
        rows = sc.execute(f"SELECT * FROM {t} ORDER BY {dcol} DESC LIMIT 12").fetchall()[::-1]
        for r in rows: print(r)
    except Exception as e: print('ERR', e)

print()
print('===== 三模型Top10次日超额复算（signal_history原始行，近5信号日）=====')
td = duckdb.connect('tushare.db', read_only=True)
sig_dates = [r[0] for r in sc.execute("SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1 DESC LIMIT 7").fetchall()]
print('信号日:', sig_dates)
tds = [r[0] for r in td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
for d in sorted(sig_dates[:6]):
    if d not in tds: continue
    i = tds.index(d)
    if i+1 >= len(tds): 
        print(d, '无次日行情'); continue
    nxt = tds[i+1]
    rows = sc.execute("SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=? AND fusion_score>=99.9 ORDER BY final_score DESC, fusion_score DESC LIMIT 10", (d,)).fetchall()
    codes = [r[0] if '.' in r[0] else r[0] for r in rows]
    # bench = 中证1000
    b0 = td.execute("SELECT close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date=?", (d,)).fetchone()
    b1 = td.execute("SELECT close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date=?", (nxt,)).fetchone()
    if not b0 or not b1: continue
    bench = (b1[0]/b0[0]-1)*100
    rets = []
    ph = ','.join('?'*len(codes))
    pr = td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [d]+codes).fetchall()
    pr1 = td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [nxt]+codes).fetchall()
    p0 = dict(pr); p1 = dict(pr1)
    for c in codes:
        if c in p0 and c in p1: rets.append((p1[c]/p0[c]-1)*100)
    if rets:
        print(d, f'Top{len(rets)} 次日等权 {sum(rets)/len(rets):+.2f}% bench {bench:+.2f}% 超额 {sum(rets)/len(rets)-bench:+.2f}%')

print()
print('===== 10d独立榜与reg10_solo账户对照：reg10_solo 持仓 =====')
lc = sqlite3.connect('ledger.db')
pos = lc.execute("SELECT * FROM strategy_positions LIMIT 3").fetchall()
pc = [c[1] for c in lc.execute("PRAGMA table_info(strategy_positions)").fetchall()]
print('strategy_positions cols:', pc)
for r in lc.execute("SELECT * FROM strategy_positions WHERE account_id='reg10_solo'").fetchall(): print(r)
