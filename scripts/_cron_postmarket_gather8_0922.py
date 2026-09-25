# -*- coding: utf-8 -*-
import duckdb, sqlite3, os, json
os.chdir('/Users/zantao/.hermes/stockdb')
c = duckdb.connect('tushare.db', read_only=True)

print('=== 指数近10日（000001.SH 上证 / 000852.SH 中证1000 / 000016.SH 上证50）===')
for ts in ['000001.SH','000852.SH','000016.SH']:
    rows = c.execute("SELECT trade_date, close, pct_chg, amount FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 10", [ts]).fetchall()
    print(ts)
    for r in reversed(rows):
        print('  ', r[0], 'close %.2f' % r[1], 'chg %+.2f%%' % r[2], 'amt(亿) %.0f' % (r[3]/1e8 if r[3] else 0))

print('=== 全市场宽度近5日（涨跌家数+两市成交额，daily表）===')
rows = c.execute("""
SELECT trade_date,
 SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END) up,
 SUM(CASE WHEN pct_chg<0 THEN 1 ELSE 0 END) dn,
 SUM(amount)/1e8 amt
FROM daily WHERE trade_date>='20260914' GROUP BY trade_date ORDER BY trade_date""").fetchall()
for r in rows: print(r[0], '涨', r[1], '跌', r[2], '涨占比 %.0f%%' % (100*r[1]/(r[1]+r[2])), '成交额(亿) %.0f' % r[3])

print('=== 昨日(0918)各榜Top10 次日(0921)表现 逐票 ===')
uni = json.load(open('analysis/opinion_universe.json'))
for bn, lst in uni['top10'].items():
    codes0 = [(x['code'] if isinstance(x,dict) else x) for x in lst][:10]
    codes = [k for k in uni['universe'] if k[:6] in codes0] if isinstance(uni['universe'], dict) else []
    print(bn, codes0)
print('universe sample:', list(uni['universe'].items())[:2] if isinstance(uni['universe'],dict) else uni['universe'][:2])

print('=== ic_window 10d/20d/40d 近12信号日 ===')
sc = sqlite3.connect('signals.db')
cols=[r[1] for r in sc.execute('PRAGMA table_info(ic_window)').fetchall()]
print(cols)
for r in sc.execute("SELECT * FROM ic_window ORDER BY signal_date DESC LIMIT 12").fetchall():
    print(list(r))

print('=== 中枢版 center_ic（若存在）===')
tabs=[r[0] for r in sc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print([t for t in tabs if 'center' in t or 'ic' in t])
