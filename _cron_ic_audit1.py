#!/usr/bin/env python3
"""IC 全链路审查：数据源表检查 2026-08-08"""
import sqlite3, duckdb

STATE = '/Users/zantao/.hermes/stockdb/state.db'
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'

s = sqlite3.connect(STATE)
t = duckdb.connect(TUSHARE, read_only=True)

print("=" * 70)
print("1) stk_factor 7/24-8/7 每日行数（WAL 损坏期 7/28-7/29 完整性）")
for r in t.execute("SELECT trade_date, COUNT(*) FROM stk_factor WHERE trade_date >= '20260724' GROUP BY 1 ORDER BY 1").fetchall():
    print(f"  {r[0]}: {r[1]} 行")

print("=" * 70)
print("2) fusion_3f_signals 7/24-8/7 强买占比（脏标签检测，正常~15%）")
for r in s.execute("SELECT REPLACE(date,'-',''), COUNT(*), SUM(CASE WHEN signal='强买' THEN 1 ELSE 0 END) FROM fusion_3f_signals WHERE REPLACE(date,'-','')>='20260724' GROUP BY 1 ORDER BY 1").fetchall():
    pct = r[2]/r[1]*100 if r[1] else 0
    flag = " ← ⚠️ 脏标签" if pct > 30 else ""
    print(f"  {r[0]}: 总{r[1]} 强买{r[2]} ({pct:.1f}%){flag}")

print("=" * 70)
print("3) factor_ic_roll 全表（fusion 行语义 + 因子行滚动）")
rows = s.execute("SELECT factor_name, as_of_date, mean_ic, n_days, win_rate, window FROM factor_ic_roll ORDER BY factor_name, as_of_date").fetchall()
cur = None
for r in rows:
    if r[0] != cur:
        cur = r[0]
        print(f"\n  [{r[0]}]")
    print(f"    {r[1]}: mean_ic={r[2]} n_days={r[3]} win_rate={r[4]} window={r[5]}")

print("=" * 70)
print("4) ic_daily 全表（4 行可信）")
for r in s.execute("SELECT signal_date, calc_date, sample_size, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date").fetchall():
    print(f"  {r[0]}: calc={r[1]} n={r[2]} fusion={r[3]} reg10={r[4]} reg20={r[5]} reg40={r[6]}")

print("=" * 70)
print("5) cmmr_ic_daily / fusion_ic_daily（含 forward_days 窗口）")
for tb in ('cmmr_ic_daily', 'fusion_ic_daily'):
    cols = [c[1] for c in s.execute(f"PRAGMA table_info({tb})").fetchall()]
    print(f"  {tb} 列: {cols}")
    for r in s.execute(f"SELECT * FROM {tb} ORDER BY date").fetchall():
        print(f"    {r}")

s.close(); t.close()
