# -*- coding: utf-8 -*-
# 盘后报告深复盘取数（只读）
import duckdb, sqlite3, json, os
os.chdir('/Users/zantao/.hermes/stockdb')
td = duckdb.connect('tushare.db', read_only=True)

print('===== 1. 指数近10日 =====')
for code, name in [('000001.SH','上证'), ('000852.SH','中证1000'), ('000016.SH','上证50'), ('399006.SZ','创业板')]:
    rows = td.execute("SELECT trade_date, close, pct_chg, amount FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 10", (code,)).fetchall()[::-1]
    print(name, [(r[0][4:], round(r[1],1), round(r[2],2), round(r[3]/1e8,0)) for r in rows])

print()
print('===== 2. 宽度/成交 近5日全市场 =====')
rows = td.execute("""
SELECT trade_date, COUNT(*), SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END),
       SUM(CASE WHEN pct_chg<-9 THEN 1 ELSE 0 END), SUM(CASE WHEN pct_chg>9 THEN 1 ELSE 0 END),
       SUM(amount)/1e8
FROM daily WHERE trade_date >= '20260914' GROUP BY trade_date ORDER BY trade_date""").fetchall()
for r in rows: print(r[0], '总数', r[1], '涨家', r[2], '跌9+', r[3], '涨9+', r[4], '亿', round(r[5],0))

print()
print('===== 3. 行业板块近10日每日平均涨幅（strength top 排行）=====')
tds = [r[0] for r in td.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260908' ORDER BY trade_date").fetchall()]
days = tds[-10:]
ph = ','.join('?'*len(days))
rows = td.execute(f"""
SELECT b.industry, d.trade_date, AVG(d.pct_chg), SUM(d.amount)/1e8
FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
WHERE d.trade_date IN ({ph}) AND b.industry IS NOT NULL AND b.industry!=''
GROUP BY b.industry, d.trade_date""", days).fetchall()
from collections import defaultdict
ind = defaultdict(dict)
amt = defaultdict(dict)
for i, d, p, a in rows:
    ind[i][d] = p; amt[i][d] = a
# 最近日强板块
last = days[-1]
rank = sorted(ind.items(), key=lambda kv: -kv[1].get(last, -99))[:15]
for name, dd in rank:
    ser = [round(dd.get(d, float('nan')),2) for d in days]
    cum5 = sum(dd.get(d,0) for d in days[-5:])
    strong = 0
    for d in days[::-1]:
        if dd.get(d, -99) > 0: strong += 1
        else: break
    print(f"{name}: 10日序列 {ser} 5日累计 {cum5:.1f} 连续强势 {strong}")

print()
print('===== 4. 主账户持仓+watchlist 距止损/止盈 =====')
lc = sqlite3.connect('ledger.db')
cols = [c[1] for c in lc.execute("PRAGMA table_info(holdings)").fetchall()]
print('holdings cols:', cols)
for r in lc.execute("SELECT * FROM holdings").fetchall(): print(r)
print('--- watchlist ---')
wcols = [c[1] for c in lc.execute("PRAGMA table_info(watchlist)").fetchall()]
print('watchlist cols:', wcols)
for r in lc.execute("SELECT * FROM watchlist").fetchall(): print(r)

print()
print('===== 5. 策略账户 meta =====')
for r in lc.execute("SELECT account_id, name, last_rebalance_date, config_json FROM strategy_accounts_meta").fetchall():
    cfg = json.loads(r[3]) if r[3] else {}
    print(r[0], r[1], 'last_rebal=', r[2], 'window=', cfg.get('rebalance_days') or cfg.get('window') or cfg.get('rebalance_window'))

print()
print('===== 6. IC 序列（近12信号日）=====')
sc = sqlite3.connect('signals.db')
for t in ['ic_daily','fusion_ic_daily','center_dual_ic_daily','cmmr_ic_daily','cmmr_top10_ic_daily']:
    cols = [c[1] for c in sc.execute(f"PRAGMA table_info({t})").fetchall()]
    print('--', t, cols)
    try:
        dcol = 'signal_date' if 'signal_date' in cols else cols[0]
        for r in sc.execute(f"SELECT * FROM {t} ORDER BY {dcol} DESC LIMIT 12").fetchall()[::-1]:
            print(r)
    except Exception as e:
        print('ERR', e)
print('-- ic_window --')
cols = [c[1] for c in sc.execute("PRAGMA table_info(ic_window)").fetchall()]
print(cols)
for r in sc.execute("SELECT * FROM ic_window ORDER BY rowid DESC LIMIT 20").fetchall()[::-1]: print(r)
