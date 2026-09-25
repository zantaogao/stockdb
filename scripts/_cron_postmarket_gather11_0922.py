# -*- coding: utf-8 -*-
import duckdb, sqlite3, os
os.chdir('/Users/zantao/.hermes/stockdb')
td = duckdb.connect('tushare.db', read_only=True)
sc = sqlite3.connect('signals.db')

print('=== 指数近6日 ===')
for code in ['000001.SH','000852.SH','000016.SH']:
    rows = td.execute("SELECT trade_date, close, pct_chg, vol FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 6", [code]).fetchall()
    print(code, [(r[0], round(r[1],1), round(r[2],2)) for r in reversed(rows)])

print('=== 0921 关键票 今日高低（防止损击穿核查）===')
for ts in ['600076.SH','301110.SH','605598.SH','600825.SH','001216.SZ']:
    r = td.execute("SELECT trade_date, open, high, low, close, pct_chg, vol FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 2", [ts]).fetchall()
    print(ts, r)

print('=== 0918+0921 申万一级全板块涨跌（找-2%放量大阴与主线）===')
for d in ['20260918','20260921']:
    rows = td.execute("""SELECT name, AVG(change_pct) p FROM board_daily WHERE date=? GROUP BY 1 ORDER BY p DESC""", [d]).fetchall()
    print(d, 'TOP5', [(n, round(p,2)) for n,p in rows[:5]])
    print(d, 'BOT5', [(n, round(p,2)) for n,p in rows[-5:]])
    print(d, '半导体', [round(p,2) for n,p in rows if n in ('半导体','元件')])

print('=== holdings 止损止盈 ===')
c = sqlite3.connect('ledger.db')
for r in c.execute("SELECT code,name,shares,avg_cost,latest_price,stop_loss,target_price FROM holdings").fetchall():
    cost, px, sl, tp = r[3], r[4], r[5], r[6]
    print(r[0], r[1], '成本%.2f 现%.2f' % (cost, px), '距止损 %.1f%%' % ((px/sl-1)*100 if sl else -1), '距止盈 %.1f%%' % ((tp/px-1)*100 if tp and px else -1))

print('=== fusion_ic_daily 1d 近12 ===')
for r in sc.execute("SELECT date, ic, n FROM fusion_ic_daily WHERE forward_days=1 ORDER BY date DESC LIMIT 12").fetchall(): print(r)
print('=== ic_daily 近10（reg列）===')
for r in sc.execute("SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall():
    print(r[0], [None if v is None else round(v,3) for v in r[1:]])
print('=== center_dual_ic_daily 近12 ===')
for r in sc.execute("SELECT * FROM center_dual_ic_daily ORDER BY 1 DESC LIMIT 12").fetchall(): print(r)
print('=== ic_window 0908后 ===')
for r in sc.execute("SELECT signal_date, ic_center_w10, ic_dual_w10 FROM ic_window WHERE signal_date>'20260907' ORDER BY signal_date").fetchall():
    print(r[0], None if r[1] is None else round(r[1],3), None if r[2] is None else round(r[2],3))
