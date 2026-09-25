# -*- coding: utf-8 -*-
import duckdb, sqlite3, os
os.chdir('/Users/zantao/.hermes/stockdb')
td = duckdb.connect('tushare.db', read_only=True)
sc = sqlite3.connect('signals.db')

print('=== 0917/0918/0921 申万一级板块涨跌（找-2%放量大阴）===')
for d in ['20260917','20260918','20260921']:
    try:
        rows = td.execute("""SELECT s.industry_name, AVG(s.pct_change) p FROM sw_daily_raw s WHERE s.ts_code LIKE '%.SW' AND REPLACE(CAST(s.date AS VARCHAR),'-','')=? GROUP BY 1 ORDER BY p DESC""", [d]).fetchall()
    except Exception as e:
        rows = []
        print('sw重算不可用:', e)
    if rows:
        print(d, 'n=', len(rows), 'TOP6', [(n, round(p,2)) for n,p in rows[:6]])
        print(d, 'BOT6', [(n, round(p,2)) for n,p in rows[-6:]])

print('=== holdings 止损止盈距离 ===')
c = sqlite3.connect('ledger.db')
for r in c.execute("SELECT code,name,shares,avg_cost,latest_price,stop_loss,target_price FROM holdings").fetchall():
    cost, px, sl, tp = r[3], r[4], r[5], r[6]
    dsl = (px/sl-1)*100 if sl else float('nan')
    dtp = (tp/px-1)*100 if tp and px else float('nan')
    print(r[0], r[1], '成本%.2f 现%.2f 止损%.2f 目标%.2f 距止损%.1f%% 距止盈%.1f%%' % (cost, px, sl or 0, tp or 0, dsl, dtp))

print('=== fusion_ic_daily 近12（按forward_days）===')
for fd in [1,5,10,20]:
    rows = sc.execute("SELECT date, ROUND(ic,4), samples FROM fusion_ic_daily WHERE forward_days=? ORDER BY date DESC LIMIT 12", [fd]).fetchall()
    print('fd=', fd, rows)
print('=== center_dual_ic_daily 结构+近10 ===')
print([x[1] for x in sc.execute("PRAGMA table_info(center_dual_ic_daily)").fetchall()])
for r in sc.execute("SELECT * FROM center_dual_ic_daily ORDER BY 1 DESC LIMIT 10").fetchall(): print(r)
print('=== ic_window 0908后 center/dual w10/w20 ===')
for r in sc.execute("SELECT signal_date, ROUND(ic_center_w10,3), ROUND(ic_dual_w10,3), ROUND(ic_center_w20,3), ROUND(ic_dual_w20,3) FROM ic_window WHERE signal_date>='20260908' ORDER BY signal_date").fetchall(): print(r)
print('=== cmmr_ic_daily 近10 ===')
print([x[1] for x in sc.execute("PRAGMA table_info(cmmr_ic_daily)").fetchall()])
for r in sc.execute("SELECT * FROM cmmr_ic_daily ORDER BY 1 DESC LIMIT 10").fetchall(): print(r)
