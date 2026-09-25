#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""午间：主账户仓位权重/现金闲置归因（只读）。"""
import sqlite3, os, urllib.request

BASE = os.path.expanduser('~/.hermes/stockdb')


def sc(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


con = sqlite3.connect('file:%s?mode=ro' % os.path.join(BASE, 'ledger.db'), uri=True)
rows = con.execute("SELECT code,name,avg_cost,shares FROM holdings WHERE status='hold'").fetchall()
cash = con.execute("SELECT cash_balance FROM account_balance WHERE account_id='main'").fetchone()[0]
con.close()

req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(sc(r[0]) for r in rows),
                             headers={'Referer': 'https://finance.sina.com.cn'})
raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk', 'ignore')
px = {}
for line in raw.strip().split('\n'):
    if 'hq_str_' not in line or '=""' in line:
        continue
    c = line.split('hq_str_')[1].split('=')[0][2:]
    p = line.split('"')[1].split(',')
    try:
        if float(p[3]) > 0:
            px[c] = float(p[3])
    except Exception:
        pass

items = []
for code, name, cost, sh in rows:
    v = px.get(code, 0)
    items.append((v * sh, code, name, sh, cost, v))
items.sort(reverse=True)
nav = cash + sum(x[0] for x in items)
print('总资产(实时) %.0f  现金 %.0f (%.1f%%)  持仓市值 %.0f (%.1f%%)  只数 %d'
      % (nav, cash, cash / nav * 100, nav - cash, (nav - cash) / nav * 100, len(items)))
print('\n仓位权重（降序）：')
for mv, code, name, sh, cost, v in items:
    print('  %-7s %-6s %7d股 %9.0f元 %5.2f%%  成本%.2f 现价%.2f' % (code, name[:6], sh, mv, mv / nav * 100, cost, v))
small = [x for x in items if x[0] / nav < 0.03]
print('\n权重<3%%的碎片仓: %d 只，合计 %.0f 元（%.1f%%）' % (len(small), sum(x[0] for x in small), sum(x[0] for x in small) / nav * 100))
for mv, code, name, sh, cost, v in small:
    print('  %s %s %.0f元 %.2f%%' % (code, name[:6], mv, mv / nav * 100))
print('\n若清掉<1%%碎片(不会自动发生, 仅测算资金效率):')
tiny = [x for x in items if x[0] / nav < 0.01]
print('   <1%%仓 %d 只 合计%.0f元' % (len(tiny), sum(x[0] for x in tiny)))
print('\n15只硬上限下：新增1只=需先卖出1只；现金%.0f元可支撑新仓上限 %.0f元/只(15%%)' % (cash, nav * 0.15))
