# -*- coding: utf-8 -*-
"""除权/复权核查：榜单里暴跌票是真实下跌还是除权（2026-09-15）"""
import duckdb, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)
print("adj_factor 列:", [c[0] for c in con.execute("DESCRIBE adj_factor").fetchall()])
codes = {
    '300908': '仲景食品', '600076': '康欣新材', '300970': '华绿生物', '301575': '艾芬达',
    '300328': '宜安科技', '301662': '宏工科技', '603090': '宏盛股份', '600785': '新华百货',
    '300864': '南大环境', '300839': '博汇股份',
}
for c, nm in codes.items():
    ts = c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ')
    af = con.execute("""SELECT trade_date, adj_factor FROM adj_factor
                        WHERE ts_code=? AND trade_date>='20260901' ORDER BY trade_date""", (ts,)).fetchall()
    print(f"\n{c} {nm} adj_factor: " + " ".join(f"{str(a[0])[4:]}:{a[1]:.4f}" for a in af))
    dv = con.execute("""SELECT end_date, cash_div, stk_div, stk_bo_rate, stk_co_rate, ex_date
                        FROM dividend WHERE ts_code=? AND ex_date>='2026-08-01'""", (ts,)).fetchall()
    if dv:
        print("   分红送转:", dv)
print("\n== 300908 仲景食品 近8日日线 ==")
for r in con.execute("""SELECT trade_date, open, high, low, close, pre_close, pct_chg, vol FROM daily
                        WHERE ts_code='300908.SZ' ORDER BY trade_date DESC LIMIT 8""").fetchall():
    print("  ", tuple(r))
con.close()
