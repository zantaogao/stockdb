# 实时对账：主账户用新浪现价重算今日盈亏，对比DB里latest_price（可能滞后）
import sqlite3, urllib.request, datetime, json
c = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
hold = c.execute("SELECT code,name,shares,avg_cost,buy_date,latest_price FROM holdings").fetchall()
def sina(codes):
    syms = [('sh' if x[0]=='6' else 'sz')+x for x in codes]
    req = urllib.request.Request('https://hq.sinajs.cn/list='+','.join(syms),
                                 headers={'Referer':'https://finance.sina.com.cn'})
    txt = urllib.request.urlopen(req, timeout=15).read().decode('gbk')
    out = {}
    for ln in txt.strip().split('\n'):
        try:
            v, d = ln.split('=',1); code = v.split('_')[-1][2:]
            f = d.strip('";').split(',')
            px = float(f[3]) or float(f[2])
            if px > 0:
                out[code] = dict(px=px, prev=float(f[2]), day=f[30], tm=f[31])
        except Exception:
            pass
    return out
px = sina(sorted({h[0] for h in hold}))
cash = c.execute("SELECT cash_balance FROM account_balance").fetchone()[0]
mv_live = sum(h[2]*px[h[0]]['px'] for h in hold if h[0] in px)
mv_db   = sum(h[2]*(h[5] or h[3]) for h in hold)
# 昨日市值口径：用今开盘前昨收算"今日涨跌额"
mv_prev = sum(h[2]*px[h[0]]['prev'] for h in hold if h[0] in px)
print('现价数据日期: %s %s' % (next(iter(px.values()))['day'], next(iter(px.values()))['tm']))
print('现金 %.0f' % cash)
print('实时市值 %.0f | DB价市值 %.0f | 昨收市值 %.0f' % (mv_live, mv_db, mv_prev))
print('今日市值涨跌 %.0f (%.2f%%)' % (mv_live-mv_prev, (mv_live/mv_prev-1)*100))
print('实时总资产 %.0f' % (cash+mv_live))
print()
print('%-8s %-6s %8s %8s %8s %7s  %s' % ('代码','名称','DB价','昨收','现价','今涨跌','成本 浮动'))
for h in sorted(hold, key=lambda x: (px.get(x[0],{}).get('px',x[5] or x[3])/x[3]-1)):
    p = px.get(h[0])
    if not p: print(h[0], h[1], '无实时价'); continue
    chg = (p['px']/p['prev']-1)*100
    pl = (p['px']/h[3]-1)*100
    flag = ' ⚠️DB价滞后' if h[5] and abs(h[5]-p['px'])/p['px'] > 0.001 else ''
    print('%-8s %-6s DB%-8s 昨%-8s 现%-8s %+6.2f%% 成本%s %+6.1f%%%s' % (
        h[0], h[1], h[5], p['prev'], p['px'], chg, h[3], pl, flag))
