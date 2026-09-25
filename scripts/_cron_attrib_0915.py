# -*- coding: utf-8 -*-
"""主账户当日归因 + trade_log + 策略账户NAV复核（2026-09-15）"""
import duckdb, sqlite3, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
lc.row_factory = sqlite3.Row
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
TODAY = '20260915'

print("== trade_log 列 ==")
print(" ", [c[1] for c in lc.execute("PRAGMA table_info(trade_log)").fetchall()])
print("\n== trade_log 最近20行 ==")
for r in lc.execute("SELECT * FROM trade_log ORDER BY rowid DESC LIMIT 20").fetchall():
    print("  ", dict(r))

print("\n== 主账户逐票当日盈亏（真实收盘价）==")
rows = lc.execute("SELECT code,name,shares,avg_cost,latest_price,buy_date FROM holdings WHERE status='hold'").fetchall()
codes = [r['code'] for r in rows]
ts = [c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ') for c in codes]
q = ','.join('?' * len(ts))
px = {}
for tc, d, c, pc in con.execute(f"""SELECT ts_code, trade_date, close, pre_close FROM daily
                                    WHERE ts_code IN ({q}) AND trade_date >= '20260912'""", ts).fetchall():
    px.setdefault(str(tc).split('.')[0], {})[str(d)] = (float(c), float(pc))
tot_today = 0
tot_pnl = 0
out = []
for r in rows:
    c0 = r['code']
    dd = px.get(c0, {})
    if TODAY not in dd:
        print(f"  {c0} 无行情")
        continue
    c, pc = dd[TODAY]
    sh = int(r['shares'])
    cost = float(r['avg_cost'])
    today = (c - pc) * sh
    cum = (c - cost) * sh
    tot_today += today
    tot_pnl += cum
    out.append((today, c0, r['name'], sh, cost, c, (c / cost - 1) * 100, today, cum, r['buy_date']))
out.sort(reverse=True)
for t, c0, nm, sh, cost, c, pct, today, cum, bd in out:
    print(f"  {c0} {nm:<8} {sh:>6}股 成本{cost:>7.2f} 收{c:>7.2f} 累计{pct:>+6.1f}%({cum:>+9.0f}元) 今日{today:>+8.0f}元 买{bd}")
print(f"\n  持仓合计: 今日 {tot_today:+,.0f}元, 累计浮盈 {tot_pnl:+,.0f}元")
print("  现金 471,336.76 ; 持仓市值 = %.0f ; 总资产 = %.0f" % (sum(px[r['code']][TODAY][0] * r['shares'] for r in rows if TODAY in px.get(r['code'], {})),
                                                        471336.759 + sum(px[r['code']][TODAY][0] * r['shares'] for r in rows if TODAY in px.get(r['code'], {}))))

print("\n== strategy_accounts 最近5行/账户 ==")
for aid in [r[0] for r in lc.execute("SELECT DISTINCT account_id FROM strategy_accounts").fetchall()]:
    rr = lc.execute("SELECT date, nav, daily_ret, market_ret, n_pos FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 3", (aid,)).fetchall()
    print(f"  {aid}: " + " | ".join(f"{r[0]} nav={r[1]:,.0f} ret={r[2]} mkt={r[3]} n={r[4]}" for r in rr))

print("\n== position_peaks（主账户）与成本比 ==")
for r in lc.execute("""SELECT p.code, p.peak_price, h.avg_cost, h.shares FROM position_peaks p
                       LEFT JOIN holdings h ON h.code=p.code AND h.status='hold'""").fetchall():
    pp, ac = r[1], r[2]
    if ac:
        print(f"  {r[0]} 峰值{pp:.2f} 成本{ac:.2f} 峰值/成本={pp/ac-1:+.1%} 回撤止盈线{pp*0.92:.2f} "
              f"{'（R3可触发）' if pp >= 1.05*ac else '（未达+5%，R3不适用）'}")

con.close(); lc.close()
