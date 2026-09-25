#!/usr/bin/env python3
"""杰理科技同行对标：蓝牙音频SoC芯片已上市公司"""
import duckdb
conn = duckdb.connect('tushare.db', read_only=True)

# 蓝牙音频 SoC 芯片同行
peers = {
    '688332.SH': '中科蓝讯',
    '688608.SH': '恒玄科技',
    '688049.SH': '炬芯科技',
    '603068.SH': '博通集成',
    '688591.SH': '泰凌微',
    '688279.SH': '峰岹科技',
    '688766.SH': '普冉股份',
}

latest = '20260731'

print(f"{'代码':<12}{'名称':<8}{'PE_ttm':>8}{'PB':>6}{'总市值亿':>8}{'流通亿':>8}{'换手%':>7}")
print('-' * 65)
for code, name in peers.items():
    r = conn.execute("""
        SELECT pe_ttm, pb, total_mv, circ_mv, turnover_rate
        FROM daily_basic WHERE ts_code=? AND trade_date=?
    """, (code, latest)).fetchone()
    # 有些可能没数据，取最近一日
    if r is None:
        r = conn.execute("""
            SELECT pe_ttm, pb, total_mv, circ_mv, turnover_rate
            FROM daily_basic WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1
        """, (code, latest)).fetchone()
    if r:
        print(f"{code:<12}{name:<8}{r[0] if r[0] else 0:>8.1f}{r[1] if r[1] else 0:>6.2f}{r[2]/1e4:>8.1f}{r[3]/1e4:>8.1f}{r[4] if r[4] else 0:>7.2f}")
    else:
        print(f"{code:<12}{name:<8}  无数据")

# 近20日行情对比
print("\n=== 近10日涨跌 ===")
for code, name in peers.items():
    rows = conn.execute("""
        SELECT trade_date, pct_chg FROM daily WHERE ts_code=?
        AND trade_date > ? ORDER BY trade_date LIMIT 10
    """, (code, '20260718')).fetchall()
    chgs = [f"{r[1]:+.1f}" for r in rows]
    if chgs:
        print(f"{name}({code}): {' '.join(chgs)}")

# 财务对比
print("\n=== 财务指标 (最新报告期) ===")
for code, name in peers.items():
    r = conn.execute("""
        SELECT end_date, eps, roe, yoy_net_profit, yoy_tr, grossprofit_margin
        FROM fina_indicator WHERE ts_code=? ORDER BY end_date DESC LIMIT 1
    """, (code,)).fetchone()
    if r:
        print(f"{name:<8} {r[0]}  EPS={r[1]} ROE={r[2]} 净利同比={r[3]}% 营收同比={r[4]}% 毛利率={r[5]}%")
    else:
        print(f"{name:<8} 无财务数据")

conn.close()
