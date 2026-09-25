# -*- coding: utf-8 -*-
import duckdb, sqlite3, os, glob
os.chdir('/Users/zantao/.hermes/stockdb')
td = duckdb.connect('tushare.db', read_only=True)
sc = sqlite3.connect('signals.db')
lc = sqlite3.connect('ledger.db')

tds = [r[0] for r in td.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260801' ORDER BY trade_date").fetchall()]

print('===== A. 主账户持仓今日涨跌（0921日线）=====')
hold = lc.execute("SELECT code,name,avg_cost,shares,target_price,stop_loss FROM holdings").fetchall()
codes = [h[0]+('.SH' if h[0].startswith('6') else '.SZ') for h in hold]
ph = ','.join('?'*len(codes))
px = {r[0]: (r[1], r[2]) for r in td.execute(f"SELECT ts_code, close, pct_chg FROM daily WHERE trade_date='20260921' AND ts_code IN ({ph})", codes).fetchall()}
prev = dict(td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date='20260918' AND ts_code IN ({ph})", codes).fetchall())
for h in hold:
    ts = h[0]+('.SH' if h[0].startswith('6') else '.SZ')
    if ts in px:
        c, pc = px[ts]
        pnl_today = (c - prev.get(ts, c)) * h[3]
        dist_tp = (h[4]/c-1)*100
        dist_sl = (c/h[5]-1)*100
        print(f"{h[1]} 今{pc:+.2f}% 今值贡献{pnl_today:+,.0f}元 距止盈{dist_tp:+.1f}% 距止损{dist_sl:+.1f}%")

print()
print('===== B. 三模型Top10次日超额复算（fusion_score降序前10）=====')
sig_dates = [r[0] for r in sc.execute("SELECT DISTINCT REPLACE(date,'-','') d FROM signal_history WHERE date>='2026-09-01' ORDER BY d DESC LIMIT 6").fetchall()]
for d in sorted(sig_dates):
    rows = sc.execute("SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=? ORDER BY fusion_score DESC LIMIT 10", (d,)).fetchall()
    cds = [r[0] if '.' in r[0] else (r[0]+('.SH' if r[0].startswith('6') else '.SZ')) for r in rows]
    if d not in tds: continue
    i = tds.index(d)
    if i+1 >= len(tds): print(d, '（当日，无次日）'); continue
    nxt = tds[i+1]
    b0 = td.execute("SELECT close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date=?", (d,)).fetchone()[0]
    b1 = td.execute("SELECT close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date=?", (nxt,)).fetchone()[0]
    bench = (b1/b0-1)*100
    ph2 = ','.join('?'*len(cds))
    p0 = dict(td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph2})", [d]+cds).fetchall())
    p1 = dict(td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph2})", [nxt]+cds).fetchall())
    rets = [(p1[c]/p0[c]-1)*100 for c in cds if c in p0 and c in p1]
    if rets: print(d, f'Top{len(rets)}次日{sum(rets)/len(rets):+.2f}% bench{bench:+.2f}% 超额{sum(rets)/len(rets)-bench:+.2f}%')

print()
print('===== C. 重评日历（交易日实算）=====')
import json
meta = lc.execute("SELECT account_id, config_json FROM strategy_accounts_meta").fetchall()
windows = {'fusion_center':20, 'center_dual':20, 'fusion_dual':15}
today_i = tds.index('20260921')
for acct, cfg in meta:
    if acct in ('fusion3f',): continue
    lr = json.loads(cfg)['last_rebalance_date'].replace('-','')
    w = windows.get(acct, 10)
    if lr not in tds:
        print(acct, 'last_rebal', lr, '非交易日?'); continue
    elapsed = tds.index(lr) - today_i - 1  # 交易日数（不含lr与今日之后）
    elapsed = today_i - tds.index(lr)
    remain = w - elapsed
    print(f"{acct} last={lr} window={w} 已过{elapsed} 剩{remain}" + (' ←明日重评' if remain<=0 else ''))

print()
print('===== D. 策略账户 R7 破线检查（现价<=成本*0.94）=====')
pos = lc.execute("SELECT account_id,code,name,avg_cost,stop_loss,target FROM strategy_positions WHERE account_id NOT IN ('fusion3f','fusion_dual')").fetchall()
cds2 = sorted({(p[1]+('.SH' if p[1].startswith('6') else '.SZ')) for p in pos})
ph3 = ','.join('?'*len(cds2))
px2 = dict(td.execute(f"SELECT ts_code, close FROM daily WHERE trade_date='20260921' AND ts_code IN ({ph3})", cds2).fetchall())
for p in pos:
    ts = p[1]+('.SH' if p[1].startswith('6') else '.SZ')
    if ts not in px2: continue
    c = px2[ts]
    cost = p[3]
    r7 = c <= cost*0.94
    sl = (c/p[4]-1)*100 if p[4] else None
    tp = (p[5]/c-1)*100 if p[5] else None
    flag = ' WARN-R7' if r7 else ''
    sls = 'NA' if sl is None else '{:+.1f}%'.format(sl)
    tps = 'NA' if tp is None else '{:+.1f}%'.format(tp)
    print(p[0], p[2], '现%.2f 本%.2f (%+.1f%%) 距止损%s 距目标%s%s' % (c, cost, (c/cost-1)*100, sls, tps, flag))

print()
print('===== E. 备份 =====')
print('backup log tail:')
print(open('db_backups/backup_20260921.log').read()[-800:])
nas = sorted(glob.glob('logs/*nas*') + glob.glob('logs/*NAS*'))
print('nas logs:', nas)
for f in nas[-2:]:
    print('--', f); print(open(f, errors='ignore').read()[-600:])
