#!/usr/bin/env python3
"""深复盘取数 0928 盘后（只读）"""
import duckdb, sqlite3, json, statistics

TD = '/Users/zantao/.hermes/stockdb'
d = duckdb.connect(f'{TD}/tushare.db', read_only=True)

print('==== 1. 指数近6日 ====')
for ts in ('000001.SH','399001.SZ','000852.SH','000016.SH','399006.SZ'):
    rows = d.execute("""SELECT trade_date, close, pct_chg, amount FROM index_daily_raw
                        WHERE ts_code=? ORDER BY trade_date DESC LIMIT 6""", [ts]).fetchall()
    print(ts, [(r[0], round(r[1],2), round(r[2],2), round((r[3] or 0)/1e8,0)) for r in rows])

print('==== 2. board_daily 可用性 ====')
try:
    cols = [r[1] for r in d.execute("PRAGMA table_info(board_daily)").fetchall()]
    print('cols:', cols[:12])
    mx = d.execute("SELECT MAX(trade_date) FROM board_daily").fetchone()[0]
    print('max date:', mx)
except Exception as e:
    print('ERR', e)

print('==== 3. 宽度近6日（涨跌家数+两市成交额） ====')
# 用 trading calendar 找最近6个交易日
dates = [r[0] for r in d.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 6").fetchall()][::-1]
for dt in dates:
    row = d.execute("""SELECT SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END),
                             SUM(CASE WHEN pct_chg<0 THEN 1 ELSE 0 END),
                             SUM(CASE WHEN pct_chg=0 OR pct_chg IS NULL THEN 1 ELSE 0 END),
                             SUM(amount) FROM daily WHERE trade_date=?""", [dt]).fetchone()
    up, dn, fl, amt = row[0] or 0, row[1] or 0, row[2] or 0, (row[3] or 0)/1e7
    print(dt, f'up={up} down={dn} flat={fl} up%={up/max(up+dn,1)*100:.0f} amt_raw={row[3]:.3g}')

print('==== 4. 持仓票近25日日线关键位 ====')
codes = ['301093','002454','301283','301237','688093','688186','603966','300658','001332','300854',
         '601615','603811','603202','300651','600076','301575','605598']
q = ",".join("'%s.SZ'" % c if not c.startswith(('6','9')) else "'%s.SH'" % c for c in codes)
for r in d.execute(f"""
  WITH x AS (SELECT ts_code, trade_date, open, high, low, close, pct_chg, vol,
             AVG(close) OVER (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) ma20,
             AVG(vol) OVER (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) v5
             FROM daily WHERE ts_code IN ({q}) AND trade_date>='20260801'),
  last AS (SELECT * FROM x WHERE trade_date='20260928'),
  hi AS (SELECT ts_code, MAX(high) h20, MIN(low) l20 FROM x WHERE trade_date>='20260825' GROUP BY ts_code)
  SELECT l.ts_code, l.close, l.pct_chg, ROUND((l.close/l.ma20-1)*100,1) dev20,
         ROUND((l.close/h.h20-1)*100,1) dist_hiq, ROUND((l.close/h.l20-1)*100,1) dist_lowq,
         ROUND(l.vol/(SELECT AVG(vol) FROM x x2 WHERE x2.ts_code=l.ts_code AND x2.trade_date<='20260922' AND x2.trade_date>='20260901'),1) volratio
  FROM last l JOIN hi h ON l.ts_code=h.ts_code ORDER BY l.pct_chg""").fetchall():
    print(r)

print('==== 5. 今日贡献/拖累票近6日 pct_chg 序列 ====')
for c in ['300854.SZ','605598.SH','301237.SZ','603811.SH','600076.SH','601615.SH']:
    rows = d.execute("SELECT trade_date, pct_chg, ROUND(vol,0) FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 6", [c]).fetchall()[::-1]
    print(c, [(r[0], r[1]) for r in rows])

d.close()

print('==== 6. IC 序列（signals.db 复算） ====')
s = sqlite3.connect(f'{TD}/signals.db')
print('-- ic_daily 近10: sig_date fusion/reg10/reg20/reg40')
for r in s.execute("SELECT signal_date, ROUND(ic_fusion,3), ROUND(ic_reg10,3), ROUND(ic_reg20,3), ROUND(ic_reg40,3) FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall()[::-1]:
    print(r)
def avg(v): return round(sum(x for x in v if x is not None)/max(len([x for x in v if x is not None]),1),3)
rows = s.execute("SELECT ic_fusion,ic_reg10,ic_reg20,ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 5").fetchall()
print('近5日均:', 'fusion', avg([r[0] for r in rows]), 'reg10', avg([r[1] for r in rows]), 'reg20', avg([r[2] for r in rows]), 'reg40', avg([r[3] for r in rows]))
rows10 = s.execute("SELECT ic_fusion,ic_reg10,ic_reg20,ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall()
print('近10日均:', 'fusion', avg([r[0] for r in rows10]), 'reg10', avg([r[1] for r in rows10]), 'reg20', avg([r[2] for r in rows10]), 'reg40', avg([r[3] for r in rows10]))

print('-- fusion_ic_daily(中枢) 近10')
rows = s.execute("SELECT date, ROUND(ic,3) FROM fusion_ic_daily ORDER BY date DESC LIMIT 10").fetchall()[::-1]
for r in rows: print(r)
print('中枢近5日均IC:', avg([r[1] for r in rows[-5:]]), '近10日:', avg([r[1] for r in rows]))

print('-- center_dual 近10')
rows = s.execute("SELECT date, ROUND(ic,3) FROM center_dual_ic_daily ORDER BY date DESC LIMIT 10").fetchall()[::-1]
for r in rows: print(r)
print('dual近5日均:', avg([r[1] for r in rows[-5:]]))

print('-- cmmr 近10')
rows = s.execute("SELECT date, ROUND(ic,3) FROM cmmr_ic_daily ORDER BY date DESC LIMIT 10").fetchall()[::-1]
for r in rows: print(r)
print('cmmr近5日均:', avg([r[1] for r in rows[-5:]]))

print('-- ic_window 近5')
for r in s.execute("SELECT signal_date, ROUND(ic_reg10_w10,3), ROUND(ic_fusion_w10,3), ROUND(ic_fusion_w40,3) FROM ic_window ORDER BY signal_date DESC LIMIT 5").fetchall():
    print(r)

print('==== 7. 策略账户 last_rebalance / meta ====')
l = sqlite3.connect(f'{TD}/ledger.db')
for r in l.execute("SELECT account_id, name, substr(config_json,1,300) FROM strategy_accounts_meta").fetchall():
    print(r)
print('==== 8. 主账户持仓+止损/目标 ====')
for r in l.execute("SELECT code,name,avg_cost,shares,latest_price,pnl_pct,target_price,stop_loss,buy_date FROM holdings WHERE status='holding' ORDER BY pnl_pct").fetchall():
    print(r)
cash = l.execute("SELECT SUM(balance) FROM account_balance").fetchone()
print('cash:', cash)

print('==== 9. signal_history 0928 top 融合分（复算榜单交叉） ====')
cols = [r[1] for r in s.execute("PRAGMA table_info(signal_history)").fetchall()]
print('sig cols:', cols)

print('==== 10. trade_cooldown 冷却期票 ====')
for r in l.execute("SELECT * FROM trade_cooldown ORDER BY rowid DESC LIMIT 10").fetchall():
    print(r)
