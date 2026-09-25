# -*- coding: utf-8 -*-
"""四榜 40 票形态诊断（2026-09-15 盘后，只读）"""
import duckdb, sqlite3, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
TODAY = '20260915'
LISTS = [
    ('三模型融合', [('600076', 12.2), ('001332', 10.4), ('300970', 10.4), ('301662', 10.2), ('301575', 9.5),
                ('301186', 9.3), ('300908', 9.1), ('603090', 9.0), ('688191', 9.0), ('603966', 8.9)]),
    ('10d独立', [('600076', 14.0), ('600785', 4.5), ('300328', 4.1), ('603186', 4.1), ('300864', 3.3),
              ('300839', 3.3), ('688503', 3.1), ('001268', 2.9), ('003018', 2.8), ('002491', 2.8)]),
    ('中枢版', [('002864', -0.027), ('002935', -0.089), ('002738', -0.138), ('001326', -0.176), ('002810', -0.182),
             ('002423', -0.190), ('002539', -0.190), ('301500', -0.197), ('002638', -0.225), ('001269', -0.227)]),
    ('中枢版+三模型', [('603409', 99.3), ('002864', 98.7), ('002865', 98.1), ('688607', 98.1), ('301590', 98.0),
                  ('300818', 97.9), ('688118', 97.5), ('300956', 97.4), ('603381', 97.2), ('688560', 97.0)]),
]
allc = sorted({c for _, l in LISTS for c, _ in l})
ts_codes = [c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ') for c in allc]
name_map = {str(r[0]).split('.')[0]: r[1] for r in con.execute("SELECT ts_code, name FROM stock_basic").fetchall()}
q = ','.join('?' * len(ts_codes))
rows = con.execute(f"""SELECT ts_code, trade_date, open, high, low, close, pre_close, pct_chg, vol
                       FROM daily WHERE ts_code IN ({q}) AND trade_date <= ? AND trade_date >= '20260701'
                       ORDER BY ts_code, trade_date""", (*ts_codes, TODAY)).fetchall()
ser = {}
for t, d, o, h, l, c, pc, p, v in rows:
    ser.setdefault(str(t).split('.')[0], []).append((str(d), float(o), float(h), float(l), float(c), float(pc), float(p or 0), float(v or 0)))

cnt = {c: sum(1 for _, l in LISTS for x, _ in l if x == c) for c in allc}
for nm, lst in LISTS:
    print("=" * 130)
    print(f"【{nm}】")
    for c, sc in lst:
        s = ser.get(c, [])
        if len(s) < 25:
            print(f"  {c} {name_map.get(c,'?')} 数据不足 {len(s)}")
            continue
        closes = [x[4] for x in s]
        pcts = [x[6] for x in s]
        vols = [x[7] for x in s]
        px = closes[-1]
        ma5, ma10 = sum(closes[-5:]) / 5, sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else ma20
        w20 = closes[-20:]
        pos20 = (px - min(w20)) / (max(w20) - min(w20)) * 100 if max(w20) > min(w20) else 50
        std = (sum((x - ma20) ** 2 for x in closes[-20:]) / 20) ** 0.5
        boll_up, boll_low = ma20 + 2 * std, ma20 - 2 * std
        bollp = (px - boll_low) / (boll_up - boll_low) * 100 if boll_up > boll_low else 50
        streak = 0
        sign = 1 if pcts[-1] > 0 else -1
        for p in reversed(pcts):
            if (p > 0 and sign == 1) or (p < 0 and sign == -1):
                streak += 1
            else:
                break
        r5 = (px / closes[-6] - 1) * 100
        r10 = (px / closes[-11] - 1) * 100
        r20 = (px / closes[-21] - 1) * 100
        big = []
        for i in range(len(s) - 1, max(len(s) - 21, 5), -1):
            av = sum(vols[i - 5:i]) / 5
            if av > 0 and vols[i] > 1.8 * av:
                big.append(f"{s[i][0][4:]}({pcts[i]:+.1f},{vols[i]/av:.1f}x)")
        gaps = []
        for i in range(len(s) - 1, max(len(s) - 21, 1), -1):
            if s[i][1] > s[i - 1][2] * 1.005:
                gaps.append(f"{s[i][0][4:]}上+{s[i][1]/s[i-1][2]-1:.1%}")
            elif s[i][1] < s[i - 1][3] * 0.995:
                gaps.append(f"{s[i][0][4:]}下{s[i][1]/s[i-1][3]-1:.1%}")
        ser12 = " ".join(f"{s[i][0][4:]}:{pcts[i]:+.1f}" for i in range(len(s) - 10, len(s)))
        print(f"  {c} {name_map.get(c,'?'):<7} 分{sc:>7} 共{cnt[c]}榜 收{px:>7.2f} 今{pcts[-1]:>+5.1f}% "
              f"5日{r5:>+6.1f}% 10日{r10:>+6.1f}% 20日{r20:>+6.1f}% MA20{(px/ma20-1)*100:>+6.1f}% 布林{bollp:>5.1f}% "
              f"20位{pos20:>5.1f}% 距20高{(px/max(w20)-1)*100:>+6.1f}% 距60高{(px/max(closes[-60:])-1)*100:>+6.1f}% 连{streak}{'涨' if sign>0 else '跌'}")
        print(f"        放量: {','.join(big[:4]) if big else '无'}   缺口: {','.join(gaps[:3]) if gaps else '无'}")
        print(f"        近10日: {ser12}")
con.close()
