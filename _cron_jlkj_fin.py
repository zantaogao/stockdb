#!/usr/bin/env python3
"""杰理科技同行财务对比 - 修正列名"""
import duckdb
conn = duckdb.connect('tushare.db', read_only=True)

# 查 fina_indicator 实际列名
cols = [r[0] for r in conn.execute("DESCRIBE fina_indicator").fetchall()]
print("fina_indicator 可用列:", [c for c in cols if 'yoy' in c.lower() or 'eps' in c.lower() or 'roe' in c.lower() or 'gross' in c.lower() or 'profit' in c.lower()][:25])

peers = {
    '688332.SH': '中科蓝讯',
    '688608.SH': '恒玄科技',
    '688049.SH': '炬芯科技',
    '603068.SH': '博通集成',
    '688591.SH': '泰凌微',
    '688279.SH': '峰岹科技',
}

print("\n=== 财务指标 (最新报告期) ===")
for code, name in peers.items():
    r = conn.execute("""
        SELECT end_date, eps, roe, netprofit_yoy, tr_yoy, grossprofit_margin, netprofit_margin
        FROM fina_indicator WHERE ts_code=? ORDER BY end_date DESC LIMIT 1
    """, (code,)).fetchone()
    if r:
        print(f"{name:<8} {r[0]}  EPS={r[1]} ROE={r[2]} 净利同比={r[3]}% 营收同比={r[4]}% 毛利率={r[5]}% 净利率={r[6]}%")
    else:
        print(f"{name:<8} 无财务数据")

conn.close()
