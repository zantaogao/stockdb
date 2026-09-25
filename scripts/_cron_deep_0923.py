#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0923 深复盘取数（只读）"""
import duckdb, sqlite3, os, json
BASE = os.path.expanduser('~/.hermes/stockdb')
TD = os.path.join(BASE, 'tushare.db')
SIG = os.path.join(BASE, 'signals.db')
LED = os.path.join(BASE, 'ledger.db')

# ---- 1. 指数近8日 ----
conn = duckdb.connect(TD, read_only=True)
print("== index_daily_raw 近8日 000001.SH / 000852.SH / 000016.SH ==")
try:
    for r in conn.execute("""SELECT ts_code, trade_date, close, pct_chg, vol, amount
        FROM index_daily_raw WHERE ts_code IN ('000001.SH','000852.SH','000016.SH')
        AND trade_date >= '20260910' ORDER BY ts_code, trade_date""").fetchall():
        print(r)
except Exception as e:
    print("ERR", e)

# ---- 2. 行业板块近10日 ----
print("\n== sw_daily_raw x stock_industry_raw 近10日 板块日涨幅 ==")
try:
    rows = conn.execute("""
    SELECT i.industry_name, d.trade_date, AVG(d.pct_chg) avg_pct, COUNT(*) n
    FROM sw_daily d JOIN stock_industry i ON d.ts_code=i.ts_code
    WHERE d.trade_date >= '20260910'
    GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    # pivot
    from collections import defaultdict
    ind = defaultdict(dict)
    for name, dt, ap, n in rows:
        ind[name][dt] = ap
    dates = sorted({r[1] for r in rows})
    print("DATES:", dates)
    # 5日累计 + 连续强势天数（从最近日往前, avg_pct>0 算强势）
    res = []
    for name, dd in ind.items():
        last5 = [dd.get(x) for x in dates[-5:] if dd.get(x) is not None]
        cum5 = sum(last5) if len(last5) == 5 else None
        streak = 0
        for x in reversed(dates):
            v = dd.get(x)
            if v is not None and v > 0: streak += 1
            elif v is not None: break
        res.append((name, cum5, streak, {d: round(dd.get(d,0),2) for d in dates[-6:]}))
    res.sort(key=lambda r: -(r[1] or -99))
    for name, cum5, streak, series in res:
        print(f"{name}\tcum5={None if cum5 is None else round(cum5,2)}\tstreak={streak}\t{series}")
except Exception as e:
    print("ERR", e)

# ---- 3. 关键票近30交易日日线 ----
codes = ['001225.SZ','688377.SH','603585.SH','300818.SZ','301590.SZ','600076.SH','300854.SZ',
         '300651.SZ','300982.SZ','688335.SH','600892.SH','000710.SZ','605598.SH','301110.SZ',
         '002763.SZ','301507.SZ','600645.SH','688659.SH','003027.SZ','300500.SZ','002961.SZ',
         '300120.SZ','300413.SZ','301575.SZ','000668.SZ','605580.SH','600551.SH','600825.SH',
         '688356.SH','003001.SZ','600892.SH','002742.SZ','002686.SZ','000890.SZ','000716.SZ',
         '301237.SZ','688093.SH','688186.SH','301053.SZ','001238.SZ','688191.SH','688776.SH']
codes = sorted(set(codes))
print("\n== 关键票近30交易日 日线（date close pct_chg vol amount）==")
try:
    qs = ",".join(f"'{c}'" for c in codes)
    rows = conn.execute(f"""SELECT ts_code, trade_date, close, pct_chg, vol, high, low
        FROM daily_raw WHERE ts_code IN ({qs}) AND trade_date >= '20260810'
        ORDER BY ts_code, trade_date""").fetchall()
    from collections import defaultdict
    per = defaultdict(list)
    for ts, dt, cl, pc, vol, hi, lo in rows:
        per[ts].append((dt, cl, pc, vol, hi, lo))
    for ts in codes:
        arr = per.get(ts, [])
        if not arr:
            print(f"--- {ts}: 无daily_raw数据")
            continue
        closes = [a[1] for a in arr]
        vols = [a[3] for a in arr]
        hi20 = max(closes[-20:]); lo20 = min(closes[-20:])
        hi_all = max(closes); lo_all = min(closes)
        v5avg = sum(vols[-6:-1])/5 if len(vols) >= 6 else None
        print(f"--- {ts} 最近{len(arr)}日")
        for dt, cl, pc, vol, hi, lo in arr[-12:]:
            vr = (vol/v5avg) if v5avg else 0
            print(f"   {dt} close={cl} pct={None if pc is None else round(pc,2)} vol_ratio_vs_prev5avg={vr:.2f}")
        print(f"   20日高={hi20} 20日低={lo20} 区间高={hi_all} 区间低={lo_all} 现价距20日高={round((closes[-1]/hi20-1)*100,1)}%")
except Exception as e:
    print("ERR", e)
conn.close()

# ---- 4. 分模型IC 近12信号日 ----
s = sqlite3.connect(SIG)
cur = s.cursor()
print("\n== ic_daily 近12 ==")
try:
    cols = [c[1] for c in cur.execute("PRAGMA table_info(ic_daily)").fetchall()]
    print("cols:", cols)
    for r in cur.execute("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 12").fetchall():
        print(r)
except Exception as e: print("ERR", e)
for t in ['fusion_ic_daily','center_dual_ic_daily','ic_window']:
    print(f"\n== {t} 近12 ==")
    try:
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        print("cols:", cols)
        for r in cur.execute(f"SELECT * FROM {t} ORDER BY rowid DESC LIMIT 12").fetchall():
            print(r)
    except Exception as e: print("ERR", e)

# ---- signal_history 0922 Top10 复核 ----
print("\n== signal_history 0922 前后 signal 行（前10高分, 复核次日超额底料）==")
try:
    for r in cur.execute("""SELECT date, stock_code, signal_type, score FROM signal_history
      WHERE REPLACE(date,'-','') IN ('20260922','20260921') ORDER BY date DESC, score DESC LIMIT 30""").fetchall():
        print(r)
except Exception as e: print("ERR", e)
s.close()

# ---- ledger: last_rebalance / watchlist ----
l = sqlite3.connect(LED)
lc = l.cursor()
print("\n== strategy_accounts_meta ==")
try:
    for r in lc.execute("SELECT * FROM strategy_accounts_meta").fetchall():
        print(r)
except Exception as e: print("ERR", e)
print("\n== watchlist ==")
try:
    for r in lc.execute("SELECT * FROM watchlist").fetchall():
        print(r)
except Exception as e: print("ERR", e)
l.close()
