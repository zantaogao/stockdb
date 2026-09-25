#!/usr/bin/env python3
"""验证 TDX 尾盘急拉过滤在两端口的实际拦截效果 2026-08-08"""
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb' / 'scripts'))

STATE = '/Users/zantao/.hermes/stockdb/state.db'
s = sqlite3.connect(STATE)

# 1. 主账户过滤集合（最新交易日急拉）
latest = s.execute("SELECT MAX(date) FROM tdx_intraday_feat").fetchone()[0]
tail30 = s.execute("SELECT code, tail30_ret FROM tdx_intraday_feat WHERE date=? AND tail30_ret > 0.015", (latest,)).fetchall()
print(f"最新交易日 {latest}: 尾盘急拉>1.5% 共 {len(tail30)} 只")
# 与 watchlist 候选交集
wl = [r[0] for r in s.execute("SELECT ts_code FROM watchlist WHERE status='watch_active'").fetchall()]
hit = [(c, r) for c, r in tail30 if c in wl]
print(f"  其中 watchlist 候选: {len(hit)} 只 {[(c, f'{r*100:+.1f}%') for c, r in hit[:5]]}")

# 2. 策略账户: 各信号源 top 候选与急拉交集
for src_tbl, date_col in [('fusion_3f_signals', 'date'), ('fusion_center_signals', 'date')]:
    try:
        d = s.execute(f"SELECT MAX(REPLACE({date_col},'-','')) FROM {src_tbl}").fetchone()[0]
        codes = [r[0] for r in s.execute(f"SELECT stock_code FROM {src_tbl} WHERE REPLACE({date_col},'-','')=? AND signal='强买'", (d,)).fetchall()]
        hit2 = [c for c, r in tail30 if c in codes]
        print(f"  策略[{src_tbl}] 信号日{d} 强买 {len(codes)} 只, 尾盘急拉拦截 {len(hit2)} 只 {hit2[:5]}")
    except Exception as e:
        print(f"  {src_tbl}: {e}")
s.close()
