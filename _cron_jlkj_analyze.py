#!/usr/bin/env python3
"""分析杰理科技：基础信息 + 行情 + 估值 + 信号 + 模型评分"""
import duckdb
import sqlite3
import json
import sys

sys.path.insert(0, '.')
from scripts.feat_tushare import get_factor_from_db

TUSHARE = 'tushare.db'
STATE = 'state.db'

conn = duckdb.connect(TUSHARE, read_only=True)
state = sqlite3.connect(STATE)

# 1. 找到杰理科技
rows = conn.execute("SELECT ts_code, name, area, industry, market, list_date FROM stock_basic WHERE name LIKE '%杰理%'").fetchall()
if not rows:
    print("未找到杰理科技")
    sys.exit(0)

for r in rows:
    print(f"基础信息: 代码={r[0]} 名称={r[1]} 地区={r[2]} 行业={r[3]} 市场={r[4]} 上市日期={r[5]}")

code = rows[0][0]
name = rows[0][1]
ts_code = code + ('.SH' if code.startswith('6') else '.SZ' if code.startswith('0') or code.startswith('3') else '.BJ')

# 2. 近期行情
print("\n=== 近20日行情 ===")
rows = conn.execute("""
    SELECT trade_date, open, high, low, close, pct_chg, vol, amount
    FROM daily WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 20
""", (ts_code,)).fetchall()
if not rows:
    rows = conn.execute("""
        SELECT trade_date, open, high, low, close, pct_chg, vol, amount
        FROM daily WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 20
    """, (code,)).fetchall()
for r in reversed(rows):
    print(f"  {r[0]}  开{r[1]:.2f} 高{r[2]:.2f} 低{r[3]:.2f} 收{r[4]:.2f} 涨跌{r[5]:.2f}% 量{r[6]} 额{r[7]:.0f}")

# 3. 估值
print("\n=== 近10日估值 (daily_basic) ===")
rows = conn.execute("""
    SELECT trade_date, pe_ttm, pb, ps_ttm, dv_ttm, total_mv, circ_mv, turnover_rate
    FROM daily_basic WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 10
""", (ts_code,)).fetchall()
if not rows:
    rows = conn.execute("""
        SELECT trade_date, pe_ttm, pb, ps_ttm, dv_ttm, total_mv, circ_mv, turnover_rate
        FROM daily_basic WHERE stock_code = ? ORDER BY trade_date DESC LIMIT 10
    """, (code,)).fetchall()
for r in reversed(rows):
    print(f"  {r[0]}  PE_ttm={r[1]}  PB={r[2]}  PS_ttm={r[3]}  股息率={r[4]}  总市值={r[5]/1e4:.1f}亿  流通市值={r[6]/1e4:.1f}亿  换手={r[7]:.2f}%")

# 4. 财务指标 (fina_indicator)
print("\n=== 财务指标 (fina_indicator 最近4期) ===")
try:
    rows = conn.execute("""
        SELECT end_date, eps, roe, grossprofit_margin, netprofit_margin,
               debt_to_assets, revenue_ps, ocft_ps, yoy_net_profit, yoy_tr
        FROM fina_indicator WHERE ts_code = ? ORDER BY end_date DESC LIMIT 4
    """, (ts_code,)).fetchall()
    for r in rows:
        print(f"  {r[0]}  EPS={r[1]}  ROE={r[2]}  毛利率={r[3]}  净利率={r[4]}  负债率={r[5]}  营收同比={r[9]}%  净利同比={r[8]}%")
except Exception as e:
    print(f"  (fina_indicator查询失败: {e})")

# 5. 信号历史
print("\n=== 信号历史 (signal_history) ===")
rows = state.execute("""
    SELECT date, reg10, reg20, reg40, fusion_score, signal, score
    FROM signal_history WHERE stock_code = ? OR stock_code = ?
    ORDER BY date DESC LIMIT 10
""", (code, ts_code)).fetchall()
for r in rows:
    print(f"  {r[0]}  reg10={r[1]} reg20={r[2]} reg40={r[3]} fusion={r[4]} signal={r[5]} score={r[6]}")

# 6. 三因子融合
print("\n=== 三因子融合评分 (fusion_3f_signals) ===")
rows = state.execute("""
    SELECT date, fusion_3f_score, signal, flow_alpha, vol_adj, ma_decay
    FROM fusion_3f_signals WHERE stock_code = ? OR stock_code = ?
    ORDER BY date DESC LIMIT 10
""", (code, ts_code)).fetchall()
for r in rows:
    print(f"  {r[0]}  fusion_3f={r[1]}  signal={r[2]}  flow_alpha={r[3]}  vol_adj={r[4]}  ma_decay={r[5]}")

# 7. 因子值 (stk_factor extra JSON)
print("\n=== 技术因子 (stk_factor, 最新) ===")
try:
    f = get_factor_from_db(code, '20260731', ['kdj_k', 'kdj_d', 'kdj_j', 'rsi_12', 'cci', 'bias_6'])
    print(f"  kdj_k={f.get('kdj_k')} kdj_d={f.get('kdj_d')} kdj_j={f.get('kdj_j')} rsi_12={f.get('rsi_12')} cci={f.get('cci')} bias_6={f.get('bias_6')}")
except Exception as e:
    print(f"  (因子查询失败: {e})")

# 8. 模型预测（当前模型评分）
print("\n=== 当前模型评分 (score_stock) ===")
try:
    from core.scoring import score_stock
    res = score_stock(code, conn=conn)
    print(f"  {res}")
except Exception as e:
    print(f"  (评分失败: {e})")

conn.close()
state.close()
