# -*- coding: utf-8 -*-
"""只读探查2：指数代码、fusion_3f 时效、IC 表最新行（2026-09-15）"""
import duckdb, sqlite3, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

print("== index_daily_raw 可用指数 ==")
for r in con.execute("SELECT ts_code, COUNT(*) n, MAX(trade_date) d FROM index_daily_raw GROUP BY 1 ORDER BY 2 DESC LIMIT 20").fetchall():
    print("  ", r)

print("\n== 宽基指数近8日 ==")
for code in ['000001.SH', '000852.SH', '399006.SZ', '000016.SH', '000905.SH', '399001.SZ']:
    rows = con.execute("SELECT trade_date, close, pct_chg, amount FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 8", (code,)).fetchall()
    if not rows:
        print(f"  {code}: 无数据")
        continue
    print(f"  {code}:")
    for t, c, p, a in rows:
        print(f"     {t}  close={c:>10.2f}  pct={p:>+6.2f}%  amt={a/1e5:>10.1f}亿" if a else f"     {t} {c} {p}")

con.close()

print("\n== signals.db 时效 ==")
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))
for t, col in [('fusion_3f_signals', 'date'), ('signal_history', 'date'), ('fusion_center_signals', 'date')]:
    try:
        rows = sc.execute(f"SELECT REPLACE({col},'-','') dd, COUNT(*) FROM {t} GROUP BY 1 ORDER BY 1 DESC LIMIT 6").fetchall()
        print(f"  {t}: {rows}")
    except Exception as e:
        print(f"  {t}: {e}")
sc.close()
