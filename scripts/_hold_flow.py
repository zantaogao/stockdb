import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
l = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
hold = l.execute("SELECT code,name FROM holdings").fetchall()
print(f"{'代码':8s} {'名称':6s} {'当日主力净/亿':>8s} {'5日累计/亿':>7s} {'净正天数':4s} {'特大单占比':6s}")
for code, name in hold:
    row = c.execute("SELECT main_net_1d_pct, main_net_5d_pct, pos_days_11d, elg_net_liq_pct FROM mf_observer_daily WHERE code LIKE ? || '.%' AND date='2026-09-04'", (code,)).fetchone()
    if row is None:
        print(f"{code:8s} {name:6s} 无数据")
        continue
    # 需要流通市值换算成绝对额 — 直接查 tushare.db
    import duckdb
    d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
    cmv = d.execute("SELECT circ_mv/10000.0 FROM daily_basic WHERE ts_code LIKE ? || '%' AND trade_date='20260904'", (code,)).fetchone()
    d.close()
    cmv = cmv[0] if cmv else None
    if cmv:
        print(f"{code:8s} {name:6s} {row[0]*cmv:10.0f} {row[1]*cmv:9.0f} {row[2]:6d}  {row[3]*100:6.2f}%")
    else:
        print(f"{code:8s} {name:6s} pct={row[0]:.4f} 5d={row[1]:.4f} 天数={row[2]} 特大={row[3]*100:.2f}%")