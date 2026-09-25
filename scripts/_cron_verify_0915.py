# -*- coding: utf-8 -*-
"""watchlist 当日观察 + ic_daily 口径 + 信号日 Top10 次日超额复核"""
import duckdb, sqlite3, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

print("== watchlist scan_date 分布（近15个不同值）==")
for r in lc.execute("SELECT scan_date, COUNT(*) FROM watchlist GROUP BY 1 ORDER BY 1 DESC LIMIT 15").fetchall():
    print("  ", r)

print("\n== watchlist scan_date 含 20260915 / 2026-09-15 ==")
for r in lc.execute("""SELECT ts_code, score, scan_date, status, entry_low, entry_high, target_price, stop_loss
                       FROM watchlist WHERE REPLACE(scan_date,'-','')='20260915' ORDER BY score DESC""").fetchall():
    print("  ", tuple(r))

print("\n== ic_daily 全部列名 + 最近3行完整 ==")
cols = [c[1] for c in sc.execute("PRAGMA table_info(ic_daily)").fetchall()]
print("  cols:", cols)
for r in sc.execute("SELECT * FROM ic_daily ORDER BY REPLACE(signal_date,'-','') DESC LIMIT 3").fetchall():
    print("  ", dict(zip(cols, r)))

print("\n== 各模型 ic_daily 近10日均值（按信号日）==")
rows = sc.execute("""SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion, ic_final
                     FROM ic_daily ORDER BY REPLACE(signal_date,'-','') DESC LIMIT 10""").fetchall()
n = len(rows)
for i, k in enumerate(['ic_reg10', 'ic_reg20', 'ic_reg40', 'ic_fusion', 'ic_final']):
    vals = [r[i + 1] for r in rows if r[i + 1] is not None]
    if vals:
        print(f"  {k}: 近{len(vals)}日均值 {sum(vals)/len(vals):+.4f}  正{sum(1 for v in vals if v>0)}/{len(vals)}  序列 " +
              " ".join(f"{r[0][-4:]}:{r[i+1]:+.3f}" for r in rows if r[i + 1] is not None))

print("\n== ic_window 各窗（成熟到 20260901）近8期均值 ==")
rows = sc.execute("""SELECT signal_date, ic_reg10_w10, ic_fusion_w10, ic_center_w10, ic_dual_w10,
                            fwd10_top_main, fwd10_top_center, fwd10_top_dual, fwd10_top
                     FROM ic_window ORDER BY REPLACE(signal_date,'-','') DESC LIMIT 8""").fetchall()
for i, k in enumerate(['ic_reg10_w10', 'ic_fusion_w10', 'ic_center_w10', 'ic_dual_w10', 'fwd10_top_main', 'fwd10_top_center', 'fwd10_top_dual', 'fwd10_top']):
    vals = [r[i + 1] for r in rows if r[i + 1] is not None]
    if vals:
        print(f"  {k}: 均 {sum(vals)/len(vals):+.4f}  正{sum(1 for v in vals if v>0)}/{len(vals)}")

print("\n== signal_history 三模型 Top10 次日超额复核（近6信号日）==")
days = [r[0] for r in sc.execute("""SELECT DISTINCT REPLACE(date,'-','') d FROM signal_history
                                    ORDER BY d DESC LIMIT 8""").fetchall()]
allday = [r[0] for r in con.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date<=? ORDER BY trade_date DESC LIMIT 30", ('20260915',)).fetchall()]
allday = list(reversed(allday))
for d in days:
    if d not in allday:
        continue
    i = allday.index(d)
    if i + 1 >= len(allday):
        print(f"  {d}: 次日未到")
        continue
    nxt = allday[i + 1]
    top = sc.execute("""SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=?
                        AND fusion_score IS NOT NULL ORDER BY fusion_score DESC LIMIT 10""", (d,)).fetchall()
    codes = [str(x[0]).split('.')[0] for x in top]
    ts = [c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ') for c in codes]
    q = ','.join('?' * len(ts))
    rr = con.execute(f"SELECT AVG(pct_chg) FROM daily WHERE trade_date=? AND ts_code IN ({q})", (nxt, *ts)).fetchone()
    mkt = con.execute("SELECT AVG(pct_chg) FROM daily WHERE trade_date=?", (nxt,)).fetchone()[0]
    if rr[0] is not None:
        print(f"  {d} → 次日{nxt}: Top10均 {rr[0]:+.2f}%  全市场 {mkt:+.2f}%  超额 {rr[0]-mkt:+.2f}%")

lc.close(); sc.close(); con.close()
