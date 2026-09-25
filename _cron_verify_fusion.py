import sqlite3, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')

print("=== fusion_3f_signals 20260803 ===")
rows = c.execute("""
    SELECT REPLACE(date,'-',''), signal, COUNT(*)
    FROM fusion_3f_signals
    WHERE REPLACE(date,'-','')='20260803'
    GROUP BY 1,2 ORDER BY 2
""").fetchall()
total = 0
for r in rows:
    print(f"  {r[0]} {r[1]:4s}: {r[2]}")
    total += r[2]
print(f"  TOTAL: {total}")

print("\n=== fusion_3f_signals 日期分布(最新5) ===")
for r in c.execute("""
    SELECT REPLACE(date,'-','') d, COUNT(*) FROM fusion_3f_signals
    GROUP BY 1 ORDER BY d DESC LIMIT 5
""").fetchall():
    print(f"  {r[0]}: {r[1]}")

print("\n=== factor_ic_roll fusion 最新3行 ===")
for r in c.execute("""
    SELECT as_of_date, factor_name, mean_ic, n_days, win_rate
    FROM factor_ic_roll
    WHERE factor_name IN ('fusion_3f_score','fusion_3f_强买')
    ORDER BY as_of_date DESC LIMIT 6
""").fetchall():
    print(f"  {r[0]} {r[1]:18s} IC={r[2]} n={r[3]} win={r[4]}")

print("\n=== 20260803 强买 top10 (fusion_3f_score DESC, flow_alpha DESC) ===")
try:
    for r in c.execute("""
        SELECT s.stock_code, s.fusion_3f_score, s.flow_alpha, s.signal
        FROM fusion_3f_signals s
        LEFT JOIN (SELECT stock_code, name, market FROM tushare.stock_basic) b
        WHERE REPLACE(s.date,'-','')='20260803' AND s.signal='强买'
        ORDER BY s.fusion_3f_score DESC, s.flow_alpha DESC LIMIT 10
    """).fetchall():
        print(f"  {r[0]} score={r[1]} flow={r[2]}")
except Exception as e:
    print("  (跳过名称JOIN查询:", e, ")")
    for r in c.execute("""
        SELECT stock_code, fusion_3f_score, flow_alpha, signal
        FROM fusion_3f_signals
        WHERE REPLACE(date,'-','')='20260803' AND signal='强买'
        ORDER BY fusion_3f_score DESC, flow_alpha DESC LIMIT 10
    """).fetchall():
        print(f"  {r[0]} score={r[1]} flow={r[2]}")

c.close()
