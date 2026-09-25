# -*- coding: utf-8 -*-
"""复权核查（2026-09-15）：找出近30日内有除权事件的票，并给出后复权真实涨幅"""
import duckdb, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
TODAY = '20260915'

LISTS = {
    '融合': ['600076', '001332', '300970', '301662', '301575', '301186', '300908', '603090', '688191', '603966'],
    '10d': ['600076', '600785', '300328', '603186', '300864', '300839', '688503', '001268', '003018', '002491'],
    '中枢': ['002864', '002935', '002738', '001326', '002810', '002423', '002539', '301500', '002638', '001269'],
    'dual': ['603409', '002864', '002865', '688607', '301590', '300818', '688118', '300956', '603381', '688560'],
}
HOLD = ['688636', '301557', '603202', '002454', '605598', '688093', '300658', '688186', '301110', '301093',
        '001332', '603966', '301237', '601615', '688191', '301283']
codes = sorted(set(sum(LISTS.values(), [])) | set(HOLD))
ts = [c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ') for c in codes]
q = ','.join('?' * len(ts))

# 日线 + 复权因子
px = {}
for t, d, o, h, l, c, pc, p in con.execute(f"""SELECT ts_code, trade_date, open, high, low, close, pre_close, pct_chg
        FROM daily WHERE ts_code IN ({q}) AND trade_date<='{TODAY}' AND trade_date>='20260701'
        ORDER BY ts_code, trade_date""", ts).fetchall():
    px.setdefault(str(t).split('.')[0], []).append((str(d), float(o), float(h), float(l), float(c), float(pc), float(p or 0)))
af = {}
for t, d, a in con.execute(f"SELECT ts_code, trade_date, adj_factor FROM adj_factor WHERE ts_code IN ({q}) AND trade_date>='20260701'", ts).fetchall():
    af.setdefault(str(t).split('.')[0], {})[str(d)] = float(a)
nm = {str(r[0]).split('.')[0]: r[1] for r in con.execute("SELECT ts_code, name FROM stock_basic").fetchall()}

print("== 近30个交易日内有除权事件(adj_factor变化)的票 ==")
events = {}
for c in codes:
    s = px.get(c, [])
    a = af.get(c, {})
    if not s or not a:
        continue
    ev = []
    for i in range(max(1, len(s) - 30), len(s)):
        d0, d1 = s[i - 1][0], s[i][0]
        if d0 in a and d1 in a and abs(a[d1] / a[d0] - 1) > 1e-6:
            ev.append((d1, a[d0], a[d1], a[d1] / a[d0]))
    if ev:
        events[c] = ev
        for d1, a0, a1, r in ev:
            print(f"  {c} {nm.get(c,'?'):<7} {d1} adj {a0:.4f}→{a1:.4f} (×{r:.4f})  除权当日 raw pct={[x[6] for x in s if x[0]==d1][0]:+.2f}%")
if not events:
    print("  无")

print("\n== 后复权真实涨幅（近3/5/10/20日）vs 原始价涨幅 ==")
for c in codes:
    s = px.get(c, [])
    a = af.get(c, {})
    if len(s) < 22 or not a:
        continue
    adj = [(x[0], x[4] * a.get(x[0], 1.0)) for x in s]
    f = lambda k: (adj[-1][1] / adj[-1 - k][1] - 1) * 100 if len(adj) > k else float('nan')
    raw = lambda k: (s[-1][4] / s[-1 - k][4] - 1) * 100 if len(s) > k else float('nan')
    flag = '⚠除权' if c in events else ''
    if c in events or abs(f(5) - raw(5)) > 3 or abs(f(20) - raw(20)) > 5:
        print(f"  {c} {nm.get(c,'?'):<7} 真实: 3日{f(3):+6.1f}% 5日{f(5):+6.1f}% 10日{f(10):+6.1f}% 20日{f(20):+6.1f}% | "
              f"原始价: 5日{raw(5):+6.1f}% 20日{raw(20):+6.1f}% {flag}")

print("\n== 除权票的真实技术位置（后复权）==")
for c, ev in events.items():
    s = px.get(c, [])
    a = af.get(c, {})
    adj = [x[4] * a.get(x[0], 1.0) for x in s]
    last = adj[-1]
    w20 = adj[-20:]
    ma20 = sum(w20) / 20
    print(f"  {c} {nm.get(c,'?'):<7} 后复权 今{last:.2f} MA20 {ma20:.2f} 距MA20 {(last/ma20-1)*100:+.1f}% "
          f"20日位 {(last-min(w20))/(max(w20)-min(w20))*100:.0f}% 距20日高 {(last/max(w20)-1)*100:+.1f}% "
          f"近10日后复权涨幅 {(last/adj[-11]-1)*100:+.1f}%")
con.close()
