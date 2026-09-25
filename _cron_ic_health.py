#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_cron_ic_health.py — 每日 IC 监控信号健康检查 (2026-08-04 v2)
步骤7: 最新信号日是否缺失
步骤8: 最近两日信号是否复制 (分数逐只相同比例 >99% = 复制)
步骤9: 上下文诊断: 市场环境/ic_daily最近行/滚动IC/分组IC/ETF IC
"""
import sqlite3, duckdb, sys
from datetime import date

DB = '/Users/zantao/.hermes/stockdb/state.db'
TD = '/Users/zantao/.hermes/stockdb/tushare.db'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

today = date.today()
today_ymd = today.strftime('%Y%m%d')
is_weekend = today.weekday() >= 5

print(f"== 健康检查 {today_ymd} ({'周末' if is_weekend else '工作日'}) ==")

# ---------- 7. 信号缺失检查 ----------
row = conn.execute("SELECT MAX(REPLACE(date,'-','')) AS d FROM signal_history").fetchone()
latest = row['d']
print(f"[7] signal_history 最新信号日: {latest}")
if latest is None:
    print("[7] ❌ 严重: signal_history 无任何数据!")
elif latest < today_ymd and not is_weekend:
    print(f"[7] ❌ 报警: 最新信号日 {latest} 早于今天 {today_ymd} 且今天非周末 → 17:30 扫描失败, 需重跑 signal_agent.py --date {today_ymd}")
else:
    print(f"[7] ✅ 信号日正常 (最新={latest}, 今天={today_ymd})")

# ---------- 8. 信号复制检查 (最近两日) ----------
rows = conn.execute("""
    SELECT REPLACE(date,'-','') AS d, COUNT(*) AS n FROM signal_history
    GROUP BY 1 ORDER BY 1 DESC LIMIT 2
""").fetchall()
print(f"[8] 最近两日行数: {[(r['d'], r['n']) for r in rows]}")
norm = lambda c: "REPLACE(REPLACE(REPLACE(" + c + ",'.SH',''),'.SZ',''),'.BJ','')"
if len(rows) >= 2:
    d_new, d_old = rows[0]['d'], rows[1]['d']
    n_new, n_old = rows[0]['n'], rows[1]['n']
    diff_pct = abs(n_new - n_old) / max(n_old, 1) * 100
    # 核心分数列 (三模型原始分, 复制事件判据)
    score_cols = ['reg10', 'reg20', 'reg40', 'fusion_score']
    col_expr = ", ".join(f"a.{c} AS a_{c}" for c in score_cols)
    join_expr = " AND ".join(f"a.{c}=b.{c}" for c in score_cols)
    q = f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN {join_expr} THEN 1 ELSE 0 END) AS same
        FROM (SELECT {norm('stock_code')} AS code, reg10, reg20, reg40, fusion_score
              FROM signal_history WHERE REPLACE(date,'-','')='{d_new}') a
        JOIN (SELECT {norm('stock_code')} AS code, reg10, reg20, reg40, fusion_score
              FROM signal_history WHERE REPLACE(date,'-','')='{d_old}') b
        ON a.code = b.code
    """
    r2 = conn.execute(q).fetchone()
    total, same = r2['total'], (r2['same'] or 0)
    ratio = same / total * 100 if total else 0
    print(f"[8] {d_new} vs {d_old}: 配对 {total} 只, 三模型分+融合分逐只相同 {same} ({ratio:.1f}%)")
    if ratio > 99:
        print(f"[8] ❌ 报警: 分数重复率 {ratio:.1f}% > 99% → 信号被复制 (如 7/30=7/29 事件), 后一日 IC 失真!")
    elif ratio > 50:
        print(f"[8] ⚠️ 警告: 重复率 {ratio:.1f}% 偏高, 建议人工核查")
    else:
        print(f"[8] ✅ 无复制迹象 (重复率 {ratio:.1f}%, 行数差 {diff_pct:.1f}% — 行数接近是宇宙稳定正常现象)")

# ---------- 9. 市场环境 ----------
tdb = duckdb.connect(TD, read_only=True)
mkt = tdb.execute("""
    SELECT COUNT(*) AS n, AVG(pct_chg) AS mean_ret,
           percentile_cont(0.10) WITHIN GROUP (ORDER BY pct_chg) AS p10,
           percentile_cont(0.90) WITHIN GROUP (ORDER BY pct_chg) AS p90,
           SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS up_ratio
    FROM daily WHERE trade_date='20260804' AND pct_chg IS NOT NULL
""").fetchone()
if mkt and mkt[0]:
    print(f"[9] 20260804 市场: n={mkt[0]}, 均值={mkt[1]:+.2f}%, p10={mkt[2]:+.2f}%, p90={mkt[3]:+.2f}%, 上涨占比={mkt[4]*100:.1f}%")
    if abs(mkt[1]) >= 2.0:
        print(f"[9] ⚠️ 大幅{'普涨' if mkt[1]>0 else '普跌'}日 (|均值|≥2%): 今日 IC/胜率波动 ±20 点属正常 (陷阱13)")
# 前一日市场 (解释 07-31 信号日 IC)
mkt2 = tdb.execute("""
    SELECT AVG(pct_chg) AS m, SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS up
    FROM daily WHERE trade_date='20260803' AND pct_chg IS NOT NULL
""").fetchone()
if mkt2 and mkt2[0]:
    print(f"[9] 20260803 市场: 均值={mkt2[0]:+.2f}%, 上涨占比={mkt2[1]*100:.1f}%")
tdb.close()

# ---------- ic_daily 最近 10 行 ----------
print("\n== ic_daily 最近 10 日 (模型 IC, Pearson T+1) ==")
for r in conn.execute("""
    SELECT signal_date, sample_size, ic_fusion, ic_reg10, ic_reg20, ic_reg40, ic_final, top_ret, bottom_ret
    FROM ic_daily ORDER BY signal_date DESC LIMIT 10
""").fetchall():
    print(f"  {r['signal_date']} n={r['sample_size']} 融合={r['ic_fusion']:+.3f} 10d={r['ic_reg10']:+.3f} 20d={r['ic_reg20']:+.3f} 40d={r['ic_reg40']:+.3f} top={r['top_ret']:+.2f}% bot={r['bottom_ret']:+.2f}%")

# ---------- factor_ic_roll (as_of_date 列) 最近 20 行 ----------
print("\n== factor_ic_roll 最近 20 行 (滚动, as_of_date) ==")
for r in conn.execute("""
    SELECT as_of_date, factor_name, mean_ic, icir, win_rate, n_days, window FROM factor_ic_roll
    ORDER BY as_of_date DESC, factor_name LIMIT 20
""").fetchall():
    print(f"  {r['as_of_date']} {r['factor_name']:<16} mean_ic={r['mean_ic']:+.3f} icir={r['icir']:+.2f} win={r['win_rate']*100:.0f}% n_days={r['n_days']}")

# ---------- factor_group_ic_daily 最近 2 个信号日对比 ----------
print("\n== factor_group_ic_daily: 最近 2 信号日对比 ==")
dates = [r[0] for r in conn.execute(
    "SELECT DISTINCT calc_date FROM factor_group_ic_daily ORDER BY calc_date DESC LIMIT 2").fetchall()]
for d in dates:
    print(f"  --- {d} ---")
    for r in conn.execute(
        "SELECT factor_name, ic, sample_size FROM factor_group_ic_daily WHERE calc_date=? ORDER BY factor_name",
        (d,)).fetchall():
        print(f"    {r['factor_name']:<16} IC={r['ic']:+.3f} n={r['sample_size']}")

# ---------- etf_ic 最近 6 行 ----------
print("\n== etf_ic 最近 6 日 ==")
try:
    for r in conn.execute("""
        SELECT calc_date, signal_date, sample_size, ic_etf, ic_spearman, top_ret FROM etf_ic
        ORDER BY signal_date DESC LIMIT 6
    """).fetchall():
        print(f"  calc={r['calc_date']} sig={r['signal_date']} n={r['sample_size']} pearson={r['ic_etf']:+.3f} spearman={r['ic_spearman']:+.3f} top={r['top_ret']:+.2f}%")
except Exception as e:
    print(f"  (etf_ic 查询失败: {e})")

conn.close()
print("\n== 健康检查完成 ==")
