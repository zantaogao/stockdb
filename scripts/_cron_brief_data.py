#!/usr/bin/env python3
"""一次性：dump 50只名单完整指标 + 大盘指数近5日，供分析用。"""
import duckdb, json
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
ts = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
tabs = [r[0] for r in ts.execute("SHOW TABLES").fetchall()]
print('index表:', [t for t in tabs if 'index' in t.lower()])
for t in tabs:
    if 'index' in t.lower():
        try:
            rows = ts.execute(f"SELECT trade_date, close, pct_chg FROM {t} WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 6").fetchall()
            print(t, '中证1000:', rows)
        except Exception as e:
            print(t, 'err', str(e)[:80])
u = json.load(open(BASE / 'analysis/opinion_universe.json'))
print('top10 keys:', list(u['top10'].keys()))
print('sample item:', u['top10'][list(u['top10'])[0]][0])
for acc in list(u['top10'].keys()):
    print('\n==' + acc)
    for item in u['top10'][acc]:
        c = item['code']
        v = u['universe'][c]
        pc, sc = v.get('signal_close'), v.get('signal_close')
        ma, bu, bl, h20 = v.get('ma20'), v.get('boll_up'), v.get('boll_low'), v.get('high20')
        dev_ma = (sc/ma-1)*100 if ma and sc else None
        pos_boll = (sc-bl)/(bu-bl)*100 if bu and bl and bu > bl else None
        print(f"{c} {v['name']} 收{sc} 5日{v.get('chg5d')}% 偏离MA20 {dev_ma:+.1f}% 布林位置{pos_boll:.0f}% 距20日高{(sc/h20-1)*100:+.1f}% 榜数{len(v['in_lists'])}")
print('\n===持仓===')
for code, v in u['universe'].items():
    for h in v['holds']:
        pc = v.get('prev_close')
        sl, tp, cost = h['stop_loss'], h['target'], h['avg_cost']
        if not pc: continue
        pl = (pc/cost-1)*100 if cost else 0
        d_sl = (pc/sl-1)*100 if sl else 0
        d_tp = (pc/tp-1)*100 if tp and tp > 0 else None
        tp_s = f" 标{tp}(距{d_tp:+.1f}%)" if d_tp is not None else ""
        print(f"{h['account']} {code} {v['name']} 昨收{pc} 本{cost} 盈亏{pl:+.1f}% 损{sl}(距{d_sl:+.1f}%){tp_s}")