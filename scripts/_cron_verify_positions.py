#!/usr/bin/env python3
# 盘前步骤2.5：持仓+榜内票日线核验（5日涨幅/距20日新高/连涨天数）
import sqlite3, duckdb, json, sys

DB = "/Users/zantao/.hermes/stockdb"
led = sqlite3.connect(DB + "/ledger.db")
td = duckdb.connect(DB + "/tushare.db", read_only=True)

# 1) 主账户持仓
hold = led.execute("SELECT code, name, shares, avg_cost, latest_price FROM holdings WHERE status='hold'").fetchall()

# 2) 榜内票（来自 draft 各榜）
lists = {
 "三模型融合": ["603585","300854","300651","300492","688171","300982","301219","301590","301259","688335"],
 "CMMR独立": ["000017","000426","000505","000523","000679","000683","000798","000890","000892","002041"],
 "CMMR+三模型": ["603585","300614","301156","002760","002858","300500","300621","003003","002809","605001"],
 "10d独立": ["001216","600743","000668","601811","600825","301237","603958","300413","300120","600551"],
 "中枢版": ["001318","300384","300854","603927","001269","301370","000514","300405","688737","002921"],
 "中枢版+三模型": ["300854","300651","300520","688737","002868","002861","300228","300887","000633","300982"],
}

def suffixed(code):
    if code.startswith("6"): return code + ".SH"
    return code + ".SZ"

cache = {}
def daily(ts):
    if ts not in cache:
        rows = td.execute("""SELECT trade_date, open, high, low, close, pct_chg FROM daily
            WHERE ts_code=? ORDER BY trade_date DESC LIMIT 25""", [ts]).fetchall()
        cache[ts] = rows[::-1]
    return cache[ts]

def analyze(code):
    ts = suffixed(code)
    rows = daily(ts)
    if len(rows) < 6:
        return None
    closes = [r[4] for r in rows]
    last = closes[-1]
    ret5 = (last / closes[-6] - 1) * 100 if len(closes) >= 6 else None
    hi20 = max(r[2] for r in rows[-20:]) if len(rows) >= 20 else max(r[2] for r in rows)
    lo20 = min(r[3] for r in rows[-20:]) if len(rows) >= 20 else min(r[3] for r in rows)
    dist_hi = (last / hi20 - 1) * 100
    dist_lo = (last / lo20 - 1) * 100
    # 连涨天数（从最新往前数 pct_chg>0）
    up = 0
    for r in rows[::-1]:
        if r[5] is not None and r[5] > 0: up += 1
        else: break
    ret3 = (last / closes[-4] - 1) * 100 if len(closes) >= 4 else None
    return dict(last=round(last,2), ret5=round(ret5,1) if ret5 is not None else None,
                ret3=round(ret3,1) if ret3 is not None else None,
                dist_hi=round(dist_hi,1), dist_lo=round(dist_lo,1), updays=up,
                lastdate=rows[-1][0])

print("=== 主账户持仓核验（成本/现价来自ledger，日线来自tushare daily）===")
codes_held = set()
for c, n, q, cp, cur in hold:
    codes_held.add(c)
    a = analyze(c)
    pnl = (cur / cp - 1) * 100 if cp else None
    if a:
        print(f"{c} {n} 成本{cp:.2f} 现{cur:.2f}({pnl:+.1f}%) 日线末{a['lastdate']} 5日{a['ret5']:+.1f}% 3日{a['ret3']:+.1f}% 距20日高{a['dist_hi']:.1f}% 距20日低{a['dist_lo']:+.1f}% 连涨{a['updays']}日")
    else:
        print(f"{c} {n} 成本{cp:.2f} 现{cur:.2f}({pnl:+.1f}%) 日线未获取")

print("\n=== 榜内票核验 ===")
for lname, codes in lists.items():
    print(f"-- {lname} --")
    for c in codes:
        tag = " [持仓交叉]" if c in codes_held else ""
        a = analyze(c)
        if a:
            print(f"{c} 末{a['lastdate']} 5日{a['ret5']:+.1f}% 3日{a['ret3']:+.1f}% 距20日高{a['dist_hi']:.1f}% 距20日低{a['dist_lo']:+.1f}% 连涨{a['updays']}日{tag}")
        else:
            print(f"{c} 日线未获取{tag}")
