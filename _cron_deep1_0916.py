import duckdb, sqlite3, json, statistics as st

con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# ---- 1. indices last 10 days ----
print("=== INDEX 10d (000001.SH SSE, 000852.SH CSI1000, 000016.SH SSE50, 399006.SZ CYB) ===")
q = """SELECT ts_code, trade_date, close, pct_chg, amount FROM index_daily_raw
WHERE ts_code IN ('000001.SH','000852.SH','000016.SH','399006.SZ') AND trade_date >= '20260901'
ORDER BY ts_code, trade_date"""
for r in con.execute(q).fetchall():
    print(r)

# ---- 2. market breadth last 5 days ----
print("\n=== BREADTH last 6 days ===")
q2 = """SELECT trade_date,
 SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END) up,
 SUM(CASE WHEN pct_chg<0 THEN 1 ELSE 0 END) dn,
 COUNT(*) tot,
 SUM(amount)/1e8 amt_yi
FROM daily WHERE trade_date >= '20260908' GROUP BY trade_date ORDER BY trade_date"""
for r in con.execute(q2).fetchall():
    print(r)

# ---- 3. sector 5d via stock_daily + stock_info industry ----
print("\n=== SECTOR daily pct_chg last 8 days (agg of stock_daily by industry) ===")
q3 = """
WITH d AS (
  SELECT s.date, b.industry, AVG(s.change_pct) avgp,
         SUM(CASE WHEN s.change_pct>0 THEN 1 ELSE 0 END)*1.0/COUNT(*) breadth
  FROM stock_daily s JOIN stock_info b ON s.stock_code=b.stock_code
  WHERE s.date >= DATE '2026-09-04' AND b.industry IS NOT NULL AND b.industry != ''
  GROUP BY 1,2
)
SELECT industry,
  STRING_AGG(FORMAT('{:%m-%d}:%+.2f', date, avgp), ' | ' ORDER BY date) traj,
  ROUND(SUM(avgp),2) cum
FROM d GROUP BY industry ORDER BY cum DESC LIMIT 20
"""
try:
    for r in con.execute(q3).fetchall():
        print(r)
except Exception as e:
    print("q3 err:", e)
print("\n--- weakest 10 ---")
try:
    q3b = q3.replace("ORDER BY cum DESC LIMIT 20","ORDER BY cum ASC LIMIT 10")
    for r in con.execute(q3b).fetchall():
        print(r)
except Exception as e:
    print(e)
con.close()

# ---- 4. IC series ----
s = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print("\n=== ic_daily last 12 (signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40, top_ret, bottom_ret) ===")
for r in s.execute("SELECT signal_date,ic_fusion,ic_reg10,ic_reg20,ic_reg40,top_ret,bottom_ret,sample_size FROM ic_daily ORDER BY signal_date DESC LIMIT 12").fetchall():
    print(r)
print("\n=== fusion_ic_daily last 12 ===")
for r in s.execute("SELECT date,ic,samples,win_rate,forward_days FROM fusion_ic_daily ORDER BY date DESC LIMIT 12").fetchall():
    print(r)
print("\n=== center_dual_ic_daily last 12 ===")
for r in s.execute("SELECT date,ic,samples,top_ret,bottom_ret,fwd10_top10 FROM center_dual_ic_daily ORDER BY date DESC LIMIT 12").fetchall():
    print(r)
print("\n=== ic_window last 10 (signal_date, ic_reg10_w10, ic_reg20_w20, ic_reg40_w40, ic_fusion_w10, ic_center_w10, ic_dual_w10, fwd10_top_center, fwd10_top_dual) ===")
for r in s.execute("SELECT signal_date,ic_reg10_w10,ic_reg20_w20,ic_reg40_w40,ic_fusion_w10,ic_center_w10,ic_dual_w10,fwd10_top_center,fwd10_top_dual FROM ic_window ORDER BY signal_date DESC LIMIT 10").fetchall():
    print(r)
s.close()

# ---- 5. universe stats for candidate stocks ----
u = json.load(open('/Users/zantao/.hermes/stockdb/analysis/opinion_universe.json'))
print("\n=== universe keys sample ===")
uni = u['universe']
print("universe size:", len(uni), "sample keys:", list(uni[0].keys()) if isinstance(uni,list) else list(uni.items())[0])
