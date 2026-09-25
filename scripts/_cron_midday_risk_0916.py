#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""午间风控口径复算（只读）：sl_eff=min(止损线,成本*0.94) / R3止盈线=峰值*0.92(需大盘≤-2%触发)。"""
import sqlite3, os, urllib.request, duckdb

BASE = os.path.expanduser('~/.hermes/stockdb')


def sc(c):
    return ('sh' if c.startswith(('6', '68', '9')) else 'sz') + c


con = sqlite3.connect('file:%s?mode=ro' % (os.path.join(BASE, 'ledger.db'),), uri=True)
rows = con.execute("SELECT code,name,avg_cost,shares,stop_loss FROM holdings WHERE status='hold'").fetchall()
peaks = {r[0]: float(r[1]) for r in con.execute("SELECT code, peak_price FROM position_peaks").fetchall()}
con.close()

req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(sc(r[0]) for r in rows),
                             headers={'Referer': 'https://finance.sina.com.cn'})
raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk', 'ignore')
px = {}
for line in raw.strip().split('\n'):
    if 'hq_str_' not in line or '=""' in line:
        continue
    code = line.split('hq_str_')[1].split('=')[0][2:]
    p = line.split('"')[1].split(',')
    try:
        if float(p[3]) > 0:
            px[code] = float(p[3])
    except Exception:
        pass

# 大盘（上证）实时
reqi = urllib.request.Request('https://hq.sinajs.cn/list=sh000001,sh000852',
                              headers={'Referer': 'https://finance.sina.com.cn'})
rawi = urllib.request.urlopen(reqi, timeout=10).read().decode('gbk', 'ignore')
print('=== 大盘开关(R3需上证≤-2%) ===')
mkt = None
for line in rawi.strip().split('\n'):
    if 'hq_str_' not in line or '=""' in line:
        continue
    c = line.split('hq_str_')[1].split('=')[0]
    p = line.split('"')[1].split(',')
    chg = (float(p[3]) / float(p[2]) - 1) * 100
    if c.endswith('000001'):
        mkt = chg
    print('  %s %.2f %+.2f%%' % (c, float(p[3]), chg))

print('\n=== 持仓风控复算(11:30实时) ===')
print('%-7s %-6s %7s %8s %8s %9s %9s %s' % ('code', 'name', '现价', '有效止损', '距止损%', 'R3止盈线', '距止盈%', '状态'))
for code, name, cost, sh, sl in rows:
    v = px.get(code)
    if not v:
        print(code, name, '无实时')
        continue
    sl_eff = min(sl, cost * 0.94) if sl and sl > 0 else 0
    d_sl = (v / sl_eff - 1) * 100 if sl_eff else None
    pk = peaks.get(code)
    tp_line = pk * 0.92 if (pk and pk >= 1.05 * cost) else None
    d_tp = (v / tp_line - 1) * 100 if tp_line else None
    st = []
    if d_sl is not None and d_sl < 2:
        st.append('⚠️贴身止损')
    if tp_line is None:
        st.append('止盈引信未启用(峰值<成本*1.05)')
    elif d_tp <= 0:
        st.append('引信已响(需大盘≤-2%)')
    elif d_tp < 2:
        st.append('⚠️贴止盈线')
    print('%-7s %-6s %7.2f %8.2f %8s %9s %9s %s' % (
        code, name[:6], v, sl_eff, ('%+.2f' % d_sl) if d_sl is not None else 'NA',
        ('%.2f' % tp_line) if tp_line else 'NA', ('%+.2f' % d_tp) if d_tp is not None else 'NA', ' '.join(st)))

print('\n=== 持仓是否在今日信号内(20260915信号日, rule5联动) ===')
sig = {}
try:
    sg = duckdb.connect(os.path.join(BASE, 'signals.db'), read_only=True)
    for r in sg.execute("SELECT stock_code, final_score FROM signal_history WHERE REPLACE(date,'-','')='20260915'").fetchall():
        sig[str(r[0]).split('.')[0]] = r[1]
    sg.close()
except Exception as e:
    print(' signals err', e)
for code, name, cost, sh, sl in rows:
    print('  %s %s 前日信号分 %s' % (code, name[:6], sig.get(code, '不在池')))
