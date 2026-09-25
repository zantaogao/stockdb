#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state.db 完整性检查（最近 8 个交易日）— 修复 Row 访问"""
import sqlite3, os

BASE = os.path.expanduser('~/.hermes/stockdb')
SD = os.path.join(BASE, 'state.db')
s = sqlite3.connect(SD)

# 最近 8 个交易日（从 tushare.db daily 取——直接硬编码避免跨库）
dates = ['20260805', '20260806', '20260807', '20260810', '20260811',
         '20260812', '20260813', '20260814']

def day_counts(table, date_col, dates=dates):
    q = (f"SELECT REPLACE({date_col},'-','') d, COUNT(*) c FROM {table} "
         f"WHERE REPLACE({date_col},'-','') >= ? GROUP BY 1 ORDER BY 1")
    d = {r[0]: r[1] for r in s.execute(q, [dates[0]]).fetchall()}
    return " ".join(f"{dt}:{d.get(dt, 0)}" for dt in dates)

print("state.db 最近 8 个交易日逐日行数:")
print("  signal_history    " + day_counts('signal_history', 'date'))
print("  fusion_3f_signals " + day_counts('fusion_3f_signals', 'date'))
print("  new_factors       " + day_counts('new_factors', 'date'))
print("  flow_alpha        " + day_counts('flow_alpha', 'date'))
print("  vol_adj           " + day_counts('vol_adj', 'date'))

# fusion_3f 信号分布（最新日）
rows = s.execute("SELECT signal, COUNT(*) c FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? GROUP BY 1",
                 [dates[-1]]).fetchall()
print(f"  fusion_3f 最新日({dates[-1]}) 分布: " + ", ".join(f"{r[0]}={r[1]}" for r in rows))

# signal_history 最新日行数 vs 8/13（确认 8/14 有数据）
r = s.execute("SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')='20260814'").fetchone()
print(f"  signal_history 8/14 行数: {r[0]}")

print("\nIC / 监控表最近 6 个日期:")
for tbl, dcol in [('ic_daily', 'signal_date'), ('cmmr_ic_daily', 'signal_date'),
                  ('fusion_ic_daily', 'signal_date'), ('etf_ic', 'signal_date'),
                  ('factor_group_ic_daily', 'calc_date'), ('ic_window', 'signal_date')]:
    try:
        rows = s.execute(
            f"SELECT DISTINCT REPLACE({dcol},'-','') d FROM {tbl} ORDER BY 1 DESC LIMIT 6").fetchall()
        print(f"  {tbl:22s} " + " ".join(r[0] for r in rows))
    except Exception as e:
        print(f"  {tbl:22s} ERROR: {e}")

# factor_ic_roll（窗口=20 最新行，fusion 行 + 因子行）
rows = s.execute(
    "SELECT factor_name, as_of_date, mean_ic, win_rate, n_days FROM factor_ic_roll "
    "WHERE window=20 ORDER BY as_of_date DESC LIMIT 8").fetchall()
print(f"\nfactor_ic_roll window=20 最新 8 行:")
for r in rows:
    print(f"  {r[0]:16s} as_of={r[1]} mean_ic={r[2]} win={r[3]} n_days={r[4]}")

# watchlist / etf_scores / tdx_intraday_feat
r = s.execute("SELECT MAX(REPLACE(scan_date,'-','')) FROM watchlist").fetchone()
print(f"  watchlist 最新 scan_date: {r[0]}")
r = s.execute("SELECT MAX(REPLACE(scan_date,'-','')) FROM etf_scores").fetchone()
print(f"  etf_scores 最新 scan_date: {r[0]}")
try:
    r = s.execute("SELECT MAX(REPLACE(date,'-','')) FROM tdx_intraday_feat").fetchone()
    print(f"  tdx_intraday_feat 最新: {r[0]}")
except Exception as e:
    print(f"  tdx_intraday_feat ERROR: {e}")

# strategy_accounts 最近 NAV
rows = s.execute("SELECT account_id, MAX(date) d FROM strategy_accounts GROUP BY 1").fetchall()
print("  strategy_accounts: " + ", ".join(f"{r[0]}={r[1]}" for r in rows))

# 持仓一致性
h = s.execute("SELECT COUNT(*) c FROM holdings").fetchone()
print(f"  holdings 行数: {h[0]}")
b = s.execute("SELECT cash_balance, total_value FROM account_balance ORDER BY rowid DESC LIMIT 1").fetchone()
if b:
    print(f"  account_balance: cash={b[0]:.2f}, total={b[1]:.2f}")

s.close()
print("\n完成。")
