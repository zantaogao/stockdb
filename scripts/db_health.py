#!/usr/bin/env python3
"""数据库完整性验证 — 一键输出各表完整度"""
import duckdb, os
from datetime import datetime, timedelta

DB = os.path.expanduser("~/.hermes/stockdb/stock.db")
conn = duckdb.connect(DB)

today = datetime.now()
today_str = today.strftime("%Y-%m-%d")

print("=" * 65)
print("📊 数据库完整性检查")
print(f"   检查时间: {today_str}")
print("=" * 65)

# ── stock_daily 日线 ──
print("\n📈 stock_daily（日线）")
total_stocks = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
total_rows = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
dr = conn.execute("SELECT MIN(date), MAX(date) FROM stock_daily").fetchone()
last_day = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
last_day_count = conn.execute(f"SELECT COUNT(*) FROM stock_daily WHERE date='{last_day}'").fetchone()[0]
print(f"  总记录: {total_rows:,} | 股票: {total_stocks}只 | 日期: {dr[0]}~{dr[1]}")
print(f"  最新交易日: {last_day} ({last_day_count}只)")

# ── stock_info 股票信息 ──
print("\n📋 stock_info（股票信息）")
info_cnt = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
no_name = conn.execute("SELECT COUNT(*) FROM stock_info WHERE stock_name IS NULL").fetchone()[0]
no_ind = conn.execute("SELECT COUNT(*) FROM stock_info WHERE industry IS NULL").fetchone()[0]
print(f"  总股票: {info_cnt} | 无名: {no_name} | 无行业: {no_ind}")

# ── money_flow 资金流 ──
print("\n💰 money_flow（资金流）")
mf_cnt = conn.execute("SELECT COUNT(*) FROM money_flow").fetchone()[0]
mf_codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM money_flow").fetchone()[0]
mf_dr = conn.execute("SELECT MIN(date), MAX(date) FROM money_flow").fetchone()
mf_per_code = conn.execute("SELECT AVG(cnt) FROM (SELECT COUNT(*) as cnt FROM money_flow GROUP BY stock_code)").fetchone()[0]

# 最新交易日覆盖
last_mf = conn.execute("SELECT MAX(date) FROM money_flow").fetchone()[0]
mf_last = conn.execute(f"SELECT COUNT(DISTINCT stock_code) FROM money_flow WHERE date='{last_mf}'").fetchone()[0]

# 检查持仓+候选股的完整性
print(f"  总记录: {mf_cnt:,} | 股票: {mf_codes}只 | 日期: {mf_dr[0]}~{mf_dr[1]}")
print(f"  最新: {last_mf} ({mf_last}只) | 均记录/股: {mf_per_code:.0f}条")

# 持仓+候选股逐一检查
print(f"\n  {'股票':<12} {'应有':>6} {'实有':>6} {'完整度':>8} {'状态'}")
key_codes = ['001288','002475','002129','002346','300308','300475','600961','300972','603626','300857','300502','688266','600221','301308']
for code in key_codes:
    name = conn.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
    name = name[0] if name else code
    actual = conn.execute(f"SELECT COUNT(*) FROM money_flow WHERE stock_code='{code}'").fetchone()[0]
    first = conn.execute(f"SELECT MIN(date) FROM money_flow WHERE stock_code='{code}'").fetchone()[0]
    # 应有天数: 从最早数据日期到最新
    expected = 0
    if first:
        expected = conn.execute(f"SELECT COUNT(*) FROM stock_daily WHERE stock_code='{code}' AND date>='{first}'").fetchone()[0]
    pct = round(actual / expected * 100, 1) if expected > 0 else 0
    status = "✅" if pct >= 95 else ("⚠️" if pct >= 50 else "❌")
    print(f"  {name:<8} {expected:>6} {actual:>6} {pct:>7.1f}% {status}")

# ── fin_income 财务数据 ──
print("\n📊 fin_income（利润表）")
fi_cnt = conn.execute("SELECT COUNT(*) FROM fin_income").fetchone()[0]
fi_codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM fin_income").fetchone()[0]
recent_q = conn.execute("SELECT MAX(report_date) FROM fin_income").fetchone()[0]
recent_cnt = conn.execute(f"SELECT COUNT(*) FROM fin_income WHERE report_date='{recent_q}'").fetchone()[0]
recent_with_roe = conn.execute(f"SELECT COUNT(*) FROM fin_income WHERE report_date='{recent_q}' AND roe IS NOT NULL").fetchone()[0]
print(f"  总记录: {fi_cnt:,} | 股票: {fi_codes}只 | 最新报告期: {recent_q}")
print(f"  最新期数据: {recent_cnt}条 | 有ROE: {recent_with_roe}条")

# ── stock_valuation 估值 ──
print("\n📐 stock_valuation（估值）")
sv_cnt = conn.execute("SELECT COUNT(*) FROM stock_valuation").fetchone()[0]
sv_codes = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_valuation").fetchone()[0]
sv_dr = conn.execute("SELECT MIN(date), MAX(date) FROM stock_valuation").fetchone()[0]
print(f"  总记录: {sv_cnt:,} | 股票: {sv_codes}只 | 最新: {sv_dr}")

# ── 整体评分 ──
print("\n" + "=" * 65)
issues = []
if mf_cnt == 0: issues.append("❌ money_flow 无数据")
if mf_codes < total_stocks * 0.5: issues.append(f"⚠️ money_flow覆盖{mf_codes}/{total_stocks}只股票")
if fi_cnt == 0: issues.append("❌ fin_income 无数据")
if recent_cnt < total_stocks * 0.5: issues.append(f"⚠️ 最新财报仅覆盖{recent_cnt}只")

if issues:
    print("发现的问题:")
    for i in issues:
        print(f"  {i}")
else:
    print("✅ 数据库整体正常")

conn.close()
