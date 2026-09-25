# -*- coding: utf-8 -*-
"""主账户近期成交 + 中证1000累计基准（2026-09-15）"""
import duckdb, sqlite3, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

print("== 主账户(main) 近40笔成交 ==")
for r in lc.execute("""SELECT trade_date, trade_time, direction, code, name, price, quantity, amount, notes
                       FROM trade_log WHERE strategy='main' ORDER BY id DESC LIMIT 40""").fetchall():
    print("  ", tuple(r))

print("\n== 中证1000 / 上证 关键日收盘 ==")
for code, nm in [('000852.SH', '中证1000'), ('000001.SH', '上证')]:
    for d in ['20260827', '20260904', '20260915']:
        r = con.execute("SELECT trade_date, close FROM index_daily_raw WHERE ts_code=? AND trade_date=?", (code, d)).fetchone()
        print(f"  {nm} {d}: {r[1] if r else 'NA'}")
    r0 = con.execute("SELECT close FROM index_daily_raw WHERE ts_code=? AND trade_date='20260827'", (code,)).fetchone()
    r1 = con.execute("SELECT close FROM index_daily_raw WHERE ts_code=? AND trade_date='20260915'", (code,)).fetchone()
    if r0 and r1:
        print(f"  → {nm} 08-27→09-15 累计 {r1[0]/r0[0]-1:+.2%}")
    r0 = con.execute("SELECT close FROM index_daily_raw WHERE ts_code=? AND trade_date='20260904'", (code,)).fetchone()
    if r0 and r1:
        print(f"  → {nm} 09-04→09-15 累计 {r1[0]/r0[0]-1:+.2%}")

print("\n== 今日 fusion_center / center_dual 卖出票当日表现 ==")
for code in ['300105', '603331', '301113', '300281', '002469', '000990', '603863', '600590', '600137', '002887']:
    ts = code + ('.SH' if code.startswith(('6', '68', '9')) else '.SZ')
    r = con.execute("SELECT close, pct_chg FROM daily WHERE ts_code=? AND trade_date='20260915'", (ts,)).fetchone()
    r5 = con.execute("SELECT close FROM daily WHERE ts_code=? AND trade_date='20260908'", (ts,)).fetchone()
    if r and r5:
        print(f"  {code}: 今日 {r[1]:+.2f}%  收{r[0]:.2f}  5日 {r[0]/r5[0]-1:+.2%}")
con.close(); lc.close()
