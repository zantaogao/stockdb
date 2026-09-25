"""查策略账户今日(20260914)是否有调仓 + 各账户状态。只读。"""
import json, os, glob

D = os.path.expanduser('~/.hermes/stockdb/sim_accounts')
for aid in ['cmmr', 'cmmr_fusion', 'fusion_center', 'center_dual', 'agent_auto', 'fusion3f', 'fusion_dual']:
    p = os.path.join(D, aid + '.json')
    if not os.path.exists(p):
        print(aid, 'NO FILE'); continue
    with open(p) as f:
        j = json.load(f)
    trades = j.get('trades') or j.get('trade_log') or []
    today = [t for t in trades if str(t.get('date', t.get('trade_date', ''))).replace('-', '') == '20260914']
    last3 = [str(t.get('date', t.get('trade_date', ''))) for t in trades[-3:]]
    nav = j.get('nav') or j.get('nav_latest')
    cash = j.get('cash')
    hold = len(j.get('positions') or j.get('holdings') or [])
    print(f"{aid:14s} trades_today={len(today)} last3dates={last3} cash={cash} pos={hold} nav={nav}")
    for t in today:
        print('    ', {k: t[k] for k in list(t)[:6]})
    # 打印顶层键，便于确认字段名
    if aid == 'cmmr':
        print('    keys:', sorted(j.keys())[:25])
