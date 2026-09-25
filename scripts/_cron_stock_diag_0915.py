# -*- coding: utf-8 -*-
"""个股形态诊断（2026-09-15 盘后，只读）：持仓 + 四榜 + 异动票"""
import duckdb, sqlite3, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
lc.row_factory = sqlite3.Row
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))
TODAY = '20260915'

LISTS = {
    '融合': ['600076', '001332', '300970', '301662', '301575', '301186', '300908', '603090', '688191', '603966'],
    '10d': ['600076', '600785', '300328', '603186', '300864', '300839', '688503', '001268', '003018', '002491'],
    '中枢': ['002864', '002935', '002738', '001326', '002810', '002423', '002539', '301500', '002638', '001269'],
    '中枢dual': ['603409', '002864', '002865', '688607', '301590', '300818', '688118', '300956', '603381', '688560'],
}
EXTRA = ['603507', '688420', '688286', '688013', '301042', '300881', '603370', '605077', '688269', '301557']

for aid, lst in LISTS.items():
    LISTS[aid] = lst

main_hold = [dict(r) for r in lc.execute("SELECT code,name,shares,avg_cost,target_price,stop_loss FROM holdings WHERE status='hold'").fetchall()]
lcode = lambda c: str(c).split('.')[0]
strat = {}
for r in lc.execute("SELECT account_id, code, name, shares, avg_cost, stop_loss, target FROM strategy_positions").fetchall():
    strat.setdefault(r[0], []).append(dict(r))

# union
tags = {}
def tag(code, t):
    tags.setdefault(code, []).append(t)

for a, lst in LISTS.items():
    for c in lst:
        tag(c, '榜:' + a)
for h in main_hold:
    tag(h['code'], '主仓')
for a, lst in strat.items():
    for p in lst:
        tag(p['code'], '策:' + a)
for c in EXTRA:
    tag(c, '异动')

codes = sorted(tags)
ts_codes = [c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ') for c in codes]
name_map = {lcode(r[0]): r[1] for r in con.execute("SELECT ts_code, name FROM stock_basic").fetchall()}

q = ','.join('?' * len(ts_codes))
rows = con.execute(f"""SELECT ts_code, trade_date, open, high, low, close, pre_close, pct_chg, vol
                       FROM daily WHERE ts_code IN ({q}) AND trade_date <= ? AND trade_date >= ?
                       ORDER BY ts_code, trade_date""", (*ts_codes, TODAY, '20260601')).fetchall()
ser = {}
for ts_code, d, o, h, l, c, pc, p, v in rows:
    ser.setdefault(lcode(ts_code), []).append((str(d), float(o), float(h), float(l), float(c), float(pc), float(p or 0), float(v or 0)))

print(f"个股诊断：共 {len(codes)} 只（数据源 tushare.daily，2026-06-01 起）")
print("字段：收/今涨/5日/10日/20日涨幅 | 距MA10/MA20 | 20日位置(0=低) | 距20日高 | 连涨跌 | 放量(vol>1.8×前5均)>2%日 | 缺口 | 近12日pct")
print("=" * 160)
for c in codes:
    s = ser.get(c, [])
    if len(s) < 25:
        print(f"{c} {name_map.get(c,'?'):<8} 数据不足({len(s)}) 标签{tags[c]}")
        continue
    closes = [x[4] for x in s]
    pcts = [x[6] for x in s]
    vols = [x[7] for x in s]
    px = closes[-1]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    win20 = closes[-20:]
    pos20 = (px - min(win20)) / (max(win20) - min(win20)) * 100 if max(win20) > min(win20) else 50
    hi20 = max(win20)
    hi60 = max(closes[-60:]) if len(closes) >= 60 else max(closes)
    lo60 = min(closes[-60:]) if len(closes) >= 60 else min(closes)
    # 连涨跌
    streak = 0
    sign = 1 if pcts[-1] > 0 else -1
    for p in reversed(pcts):
        if (p > 0 and sign == 1) or (p < 0 and sign == -1):
            streak += 1
        else:
            break
    r5 = (px / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    r10 = (px / closes[-11] - 1) * 100 if len(closes) >= 11 else 0
    r20 = (px / closes[-21] - 1) * 100 if len(closes) >= 21 else 0
    # 放量日
    big = []
    for i in range(len(s) - 1, max(len(s) - 31, 5), -1):
        av = sum(vols[i - 5:i]) / 5
        if av > 0 and vols[i] > 1.8 * av:
            big.append(f"{s[i][0][4:]}({pcts[i]:+.1f}%,{vols[i]/av:.1f}x)")
    # 缺口
    gaps = []
    for i in range(len(s) - 1, max(len(s) - 31, 1), -1):
        if s[i][1] > s[i - 1][2] * 1.005:
            gaps.append(f"{s[i][0][4:]}上跳{s[i][1]/s[i-1][2]-1:+.1%}")
        elif s[i][1] < s[i - 1][3] * 0.995:
            gaps.append(f"{s[i][0][4:]}下跳{s[i][1]/s[i-1][3]-1:+.1%}")
    series12 = " ".join(f"{s[i][0][4:]}:{pcts[i]:+.1f}" for i in range(len(s) - 12, len(s)))
    print(f"{c} {name_map.get(c,'?'):<8} 收{px:>7.2f} 今{pcts[-1]:>+5.1f}% 5日{r5:>+6.1f}% 10日{r10:>+6.1f}% 20日{r20:>+6.1f}% | "
          f"MA10{(px/ma10-1)*100:>+5.1f}% MA20{(px/ma20-1)*100:>+5.1f}% | 20位{pos20:>5.1f}% 距20高{(px/hi20-1)*100:>+5.1f}% 距60高{(px/hi60-1)*100:>+5.1f}% 60低{(px/lo60-1)*100:>+5.1f}% | "
          f"连{streak}{'涨' if sign>0 else '跌'} | 放量{','.join(big[:4]) if big else '无'} | 缺{','.join(gaps[:3]) if gaps else '无'}")
    print(f"      {tags[c]}")
    print(f"      近12日: {series12}")

con.close(); lc.close(); sc.close()
