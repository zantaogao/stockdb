#!/usr/bin/env python3
"""2026-09-16 M2 手动碎仓清理（用户指令：卖出全部碎仓，含M2）。
口径同本机 DUST_CLEAN_RATIO：市值 < (cash+持仓市值)×1% → 按收盘价卖出入账。
只跑一次，幂等：trades 里已有当日'手动碎仓清理'记录的票跳过。"""
import json, glob, os, urllib.request, datetime

BASE = os.path.expanduser('~/.hermes/stockdb/sim_accounts')
TODAY = '20260916'
TODAY_ISO = '2026-09-16'
NOW = datetime.datetime.now().isoformat(timespec='seconds')
RATIO = 0.01

def sina(codes):
    syms = [('sh' if c[0] == '6' else 'sz') + c for c in codes]
    req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(syms),
                                 headers={'Referer': 'https://finance.sina.com.cn'})
    txt = urllib.request.urlopen(req, timeout=15).read().decode('gbk')
    out = {}
    for ln in txt.strip().split('\n'):
        try:
            v, d = ln.split('=', 1)
            code = v.split('_')[-1][2:]
            f = d.strip('";').split(',')
            px = float(f[3]) or float(f[2])
            if px > 0:
                out[code] = px
        except Exception:
            pass
    return out

grand, gamt = 0, 0.0
for f in sorted(glob.glob(BASE + '/*.json')):
    d = json.load(open(f))
    pos = d.get('positions') or []
    if not pos:
        continue
    acct = d.get('id') or os.path.basename(f)
    done = {t['code'] for t in d.get('trades', [])
            if t.get('date') in (TODAY, TODAY_ISO) and '手动碎仓清理' in str(t.get('reason', ''))}
    pm = sina(sorted({p['code'] for p in pos}))
    nav = float(d['cash']) + sum(p['shares'] * pm.get(p['code'], p['avg_cost']) for p in pos)
    thr = nav * RATIO
    keep, sold = [], []
    for p in pos:
        px = pm.get(p['code'])
        if px and p['code'] not in done and p['shares'] * px < thr:
            sold.append((p, px))
        else:
            keep.append(p)
    if not sold:
        print(f'{acct}: 无碎仓')
        continue
    for p, px in sold:
        amt = p['shares'] * px
        d['cash'] = round(float(d['cash']) + amt, 2)
        d['trades'].append({
            'date': TODAY, 'action': '卖出', 'code': p['code'], 'name': p['name'],
            'price': round(px, 3), 'shares': p['shares'], 'amount': round(amt, 2),
            'pnl_pct': round((px / p['avg_cost'] - 1) * 100, 2) if p.get('avg_cost') else None,
            'reason': '手动碎仓清理（2026-09-16 用户指令，权重<1%）', 'trade_time': NOW})
        grand += 1; gamt += amt
        print(f"[{acct}] 卖 {p['code']} {p['name']} {p['shares']}股 @{px:.2f} = {amt:,.0f}元 盈亏{(px/p['avg_cost']-1)*100:+.1f}%")
    d['positions'] = keep
    d['updated_at'] = NOW
    os.rename(f, f + '.bak.20260916_dust')
    json.dump(d, open(f, 'w'), ensure_ascii=False, indent=2)
print(f'DONE 共卖{grand}笔 回收{gamt:,.0f}元')
