import sqlite3, os, urllib.request, time
LED = os.path.expanduser('~/.hermes/stockdb/ledger.db')
con = sqlite3.connect(LED); con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute("SELECT account_id, code, name, shares, avg_cost FROM strategy_positions")]
codes = sorted({r['code'] for r in rows})
print("holdings codes:", len(codes))

def sina(codes):
    out = {}
    for i in range(0, len(codes), 60):
        chunk = codes[i:i+60]
        lst = []
        for c in chunk:
            c6 = c.split('.')[0] if '.' in c else c
            pre = 'sh' if c6[0] in '65' or c6.startswith('9') else 'sz'
            lst.append(pre + c6)
        url = "https://hq.sinajs.cn/list=" + ",".join(lst)
        req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
        txt = urllib.request.urlopen(req, timeout=10).read().decode('gbk', 'ignore')
        for line in txt.strip().split('\n'):
            if '="' not in line: continue
            key = line.split('=')[0].split('_')[-1]
            body = line.split('="')[1].rstrip('";')
            f = body.split(',')
            if len(f) > 3:
                out[key[2:]] = (f[0], float(f[1] or 0), float(f[2] or 0), float(f[3] or 0))
        time.sleep(0.2)
    return out

q = sina(codes)
print("quoted:", len(q))
agg = {}
for r in rows:
    c6 = r['code'].split('.')[0]
    v = q.get(c6)
    if not v:
        print("MISSING QUOTE", r['account_id'], r['code'], r['name']); continue
    name, prev_close, cur, openp = v
    if prev_close <= 0:
        print("BAD PREV", r['code'], v); continue
    pnl = r['shares'] * (cur - prev_close)
    a = agg.setdefault(r['account_id'], {'pnl': 0.0, 'cost': 0.0, 'mv': 0.0, 'worst': []})
    a['pnl'] += pnl
    a['cost'] += r['shares'] * r['avg_cost']
    a['mv'] += r['shares'] * cur
    a['worst'].append((round((cur/prev_close-1)*100, 2), r['code'], r['name'], round(pnl, 0)))

print("\n=== 今日持仓浮盈变动 (实时价 vs 昨收) ===")
for aid, a in sorted(agg.items()):
    print(f"{aid:14s} 持仓市值={a['mv']:>12,.0f}  成本={a['cost']:>12,.0f}  今日浮动={a['pnl']:>+11,.0f}")
print("\n=== 各账户今日跌幅前三 ===")
for aid, a in sorted(agg.items()):
    w = sorted(a['worst'])[:3]
    print(aid, w)
print("\n=== 全持仓最差10只 ===")
allw = sorted([x for a in agg.values() for x in a['worst']])[:10]
for x in allw: print(x)
