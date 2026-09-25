#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性检查：这几天数据库更新是否完整（2026-08-14）
只读 tushare.db（DuckDB）+ state.db（SQLite），无任何写入。"""
import duckdb, sqlite3, os, glob

BASE = os.path.expanduser('~/.hermes/stockdb')
TD = os.path.join(BASE, 'tushare.db')
SD = os.path.join(BASE, 'state.db')

print("=" * 70)
print("tushare.db 完整性检查（最近 8 个交易日逐日行数）")
print("=" * 70)
conn = duckdb.connect(TD, read_only=True)

# 最近 8 个交易日（从 daily 取）
dates = [r[0] for r in conn.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 8").fetchall()]
dates.reverse()
print(f"最近交易日序列: {dates}")

def day_counts(table, date_col='trade_date'):
    rows = conn.execute(
        f"SELECT {date_col}, COUNT(*) FROM {table} WHERE {date_col} >= ? GROUP BY 1 ORDER BY 1",
        [dates[0]]).fetchall()
    d = {r[0]: r[1] for r in rows}
    out = []
    for dt in dates:
        out.append(f"{dt}:{d.get(dt, 0)}")
    return " ".join(out)

for tbl in ['daily', 'daily_basic', 'stk_factor', 'fund_daily']:
    try:
        print(f"  {tbl:14s} {day_counts(tbl)}")
    except Exception as e:
        print(f"  {tbl:14s} ERROR: {e}")

# index_daily_raw 最近 8 天（逐日行数 + 覆盖指数数）
try:
    rows = conn.execute(
        "SELECT trade_date, COUNT(DISTINCT ts_code) FROM index_daily_raw "
        "WHERE trade_date >= ? GROUP BY 1 ORDER BY 1", [dates[0]]).fetchall()
    print("  index_daily_raw: " + " ".join(f"{r[0]}:{r[1]}指数" for r in rows))
except Exception as e:
    print(f"  index_daily_raw ERROR: {e}")

# stk_factor 最新日期（确认滞后口径）
print(f"  stk_factor 全局 MAX: {conn.execute('SELECT MAX(trade_date) FROM stk_factor').fetchone()[0]}")

# 财报表最新报告期
for tbl in ['fin_income', 'fin_balancesheet', 'fin_cashflow']:
    try:
        r = conn.execute(f"SELECT end_date, COUNT(*) FROM {tbl} GROUP BY 1 ORDER BY 1 DESC LIMIT 2").fetchall()
        print(f"  {tbl:16s} 最新报告期: " + ", ".join(f"{x[0]}({x[1]}只)" for x in r))
    except Exception as e:
        print(f"  {tbl:16s} ERROR: {e}")

# stock_basic 总行数
print(f"  stock_basic 总行数: {conn.execute('SELECT COUNT(*) FROM stock_basic').fetchone()[0]}")

# 交易日历连续性：最近 10 个交易日之间是否有缺失（对比 daily 与预期）
conn.close()

# WAL 残留检查
print("\ntushare.db 文件状态:")
for f in sorted(glob.glob(TD + "*")):
    sz = os.path.getsize(f) / 1e9
    print(f"  {os.path.basename(f)}: {sz:.2f} GB")

print("\n" + "=" * 70)
print("state.db 完整性检查（最近 8 个交易日）")
print("=" * 70)
s = sqlite3.connect(SD)
s.row_factory = sqlite3.Row

def sday_counts(table, date_col, dates=dates, fmt='strip'):
    """date 列可能是 YYYYMMDD 或 YYYY-MM-DD，统一 REPLACE 比较"""
    q = (f"SELECT REPLACE({date_col},'-','') d, COUNT(*) FROM {table} "
         f"WHERE REPLACE({date_col},'-','') >= ? GROUP BY 1 ORDER BY 1")
    rows = s.execute(q, [dates[0]]).fetchall()
    d = {r['d']: r['c'] for r in rows}
    return " ".join(f"{dt}:{d.get(dt, 0)}" for dt in dates)

print("  signal_history    " + sday_counts('signal_history', 'date'))
print("  fusion_3f_signals " + sday_counts('fusion_3f_signals', 'date'))
print("  new_factors       " + sday_counts('new_factors', 'date'))
print("  flow_alpha        " + sday_counts('flow_alpha', 'date'))
print("  vol_adj           " + sday_counts('vol_adj', 'date'))

# fusion_3f 信号分布（最新日）
r = s.execute("SELECT signal, COUNT(*) FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? GROUP BY 1",
              [dates[-1]]).fetchall()
print(f"  fusion_3f 最新日({dates[-1]}) 分布: " + ", ".join(f"{x['signal']}={x['c']}" for x in r))

# IC 类表（信号日 vs 计算日）
print("\nIC / 监控表最近 6 行:")
for tbl, dcol in [('ic_daily', 'signal_date'), ('cmmr_ic_daily', 'signal_date'),
                  ('fusion_ic_daily', 'signal_date'), ('etf_ic', 'signal_date'),
                  ('factor_group_ic_daily', 'calc_date'), ('factor_ic_roll', 'as_of_date'),
                  ('ic_window', 'signal_date')]:
    try:
        rows = s.execute(
            f"SELECT DISTINCT REPLACE({dcol},'-','') d FROM {tbl} ORDER BY 1 DESC LIMIT 6").fetchall()
        print(f"  {tbl:22s} " + " ".join(x['d'] for x in rows))
    except Exception as e:
        print(f"  {tbl:22s} ERROR: {e}")

# watchlist
r = s.execute("SELECT MAX(REPLACE(scan_date,'-','')) FROM watchlist").fetchone()
print(f"  watchlist 最新 scan_date: {r[0]}")

# etf_scores
r = s.execute("SELECT MAX(REPLACE(scan_date,'-','')) FROM etf_scores").fetchone()
print(f"  etf_scores 最新 scan_date: {r[0]}")

# tdx_intraday_feat 最新日期
try:
    r = s.execute("SELECT MAX(REPLACE(date,'-','')) FROM tdx_intraday_feat").fetchone()
    print(f"  tdx_intraday_feat 最新: {r[0]}")
except Exception as e:
    print(f"  tdx_intraday_feat ERROR: {e}")

# strategy_accounts 最近 NAV
rows = s.execute("SELECT account_id, MAX(date) d FROM strategy_accounts GROUP BY 1").fetchall()
print("  strategy_accounts: " + ", ".join(f"{x['account_id']}={x['d']}" for x in rows))

# 持仓一致性（holdings vs account_balance）
h = s.execute("SELECT COUNT(*) c, COALESCE(SUM(quantity*current_price),0) v FROM holdings").fetchone()
b = s.execute("SELECT * FROM account_balance ORDER BY rowid DESC LIMIT 1").fetchone()
print(f"  holdings: {h['c']} 只, 市值约 {h['v']:.0f}")
if b:
    print(f"  account_balance: cash={b['cash_balance']}, total_value={b['total_value']}")

s.close()
print("\n完成。")
