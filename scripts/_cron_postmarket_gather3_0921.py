# -*- coding: utf-8 -*-
import duckdb, sqlite3, json, os
os.chdir('/Users/zantao/.hermes/stockdb')
sc = sqlite3.connect('signals.db')
td = duckdb.connect('tushare.db', read_only=True)

def full(c):
    c = c if '.' in c else c
    if '.' not in c:
        if c.startswith(('6','9','68')): c += '.SH'
        else: c += '.SZ'
    return c

print('===== 三模型Top10次日超额复算 =====')
sig_dates = [r[0] for r in sc.execute("SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1 DESC LIMIT 7").fetchall()]
tds = [r[0] for r in td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
for d in sorted(sig_dates[:6]):
    if d not in tds: continue
    i = tds.index(d)
    if i+1 >= len(tds):
        print(d, '无次日行情'); continue
    nxt = tds[i+1]
    rows = sc.execute("SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=? AND fusion_score>=99.9 ORDER BY final_score DESC, fusion_score DESC LIMIT 10", (d,)).fetchall()
    codes = [full(r[0]) for r in rows]
    if not codes: print(d,'no rows'); continue
    b0 = td.execute("SELECT close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date=?", (d,)).fetchone()
    b1 = td.execute("SELECT close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date=?", (nxt,)).fetchone()
    if not b0 or not b1: print(d,'no bench'); continue
    bench = (b1[0]/b0[0]-1)*100
    ph = ','.join('?'*len(codes))
    p0 = dict(td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [d]+codes).fetchall())
    p1 = dict(td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [nxt]+codes).fetchall())
    rets = [(p1[c]/p0[c]-1)*100 for c in codes if c in p0 and c in p1]
    if rets:
        print(d, f'Top{len(rets)} 次日等权 {sum(rets)/len(rets):+.2f}% bench {bench:+.2f}% 超额 {sum(rets)/len(rets)-bench:+.2f}%')

print()
print('===== 中枢版 top15% 次日/5日 超额（fusion_center_signals）=====')
cols = [c[1] for c in sc.execute("PRAGMA table_info(fusion_center_signals)").fetchall()]
print('cols:', cols)
dcol = 'signal_date' if 'signal_date' in cols else ('date' if 'date' in cols else cols[0])
for r in sc.execute(f"SELECT * FROM fusion_center_signals ORDER BY {dcol} DESC LIMIT 3").fetchall(): print(r)

print()
print('===== reg10_solo 持仓（对照10d独立榜）=====')
lc = sqlite3.connect('ledger.db')
pc = [c[1] for c in lc.execute("PRAGMA table_info(strategy_positions)").fetchall()]
print('cols:', pc)
for r in lc.execute("SELECT * FROM strategy_positions WHERE account_id='reg10_solo' ORDER BY 2").fetchall(): print(r)

print()
print('===== 各策略账户最近NAV（strategy_accounts_daily?）=====')
tabs = [r[0] for r in lc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
navt = [t for t in tabs if 'nav' in t or 'daily' in t]
print('nav tables:', navt)
