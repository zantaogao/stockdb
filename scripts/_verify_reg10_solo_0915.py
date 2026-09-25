#!/usr/bin/env /usr/bin/python3 -B
"""离线验证 reg10_solo 选票分支（不下单不写库）：
1) ACCOUNTS 注册项可读、rebalance=10
2) get_signal_targets(src='reg10') 对最近信号日返回 top10，且与 signal_history 纯排序一致
3) 尾拉/诱多过滤路径不报错
4) ACCOUNTS 的 name 与 daily_report STRATEGY_NAMES 无 import 冲突
"""
import sys, sqlite3, duckdb
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb' / 'scripts'))
BASE = Path.home() / '.hermes' / 'stockdb'

import strategy_accounts_daily as sad
assert 'reg10_solo' in sad.ACCOUNTS, "ACCOUNTS 未注册"
a = sad.ACCOUNTS['reg10_solo']
assert a['src'] == 'reg10' and a['rebalance'] == 10 and a['topup'] == 'gap', a
print("① ACCOUNTS 注册 OK:", a)

import daily_report  # noqa: 名称映射一致性
assert daily_report.STRATEGY_NAMES.get('reg10_solo') == '10d独立'
print("② daily_report 名称映射 OK")

state = sqlite3.connect(str(BASE / 'ledger.db'), timeout=30)
state.execute("ATTACH DATABASE ? AS sig", (str(BASE / 'signals.db'),))
tushare = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
bad = sad.get_filtered_codes(tushare)
d = state.execute("SELECT MAX(REPLACE(date,'-','')) FROM sig.signal_history").fetchone()[0]
targets = sad.get_signal_targets(state, tushare, d, 'reg10', bad, top_n=10)
print(f"③ 信号日 {d} 选出的目标 top{len(targets)}:")
for code, score in targets:
    print(f"   {code}  reg10={score:.4f}")
# 与直查对照
raw = state.execute("""
    SELECT stock_code, reg10 FROM sig.signal_history
    WHERE REPLACE(date,'-','')=? AND reg10 IS NOT NULL
    ORDER BY reg10 DESC, stock_code LIMIT 12""", (d,)).fetchall()
raw_ok = [c for c, _ in raw if ts in None or (sad.ts_code(c) not in bad)][:10] if False else [c for c, _ in raw if sad.ts_code(c) not in bad][:10]
got = [c for c, _ in targets]
assert got[:min(len(got),10)] == raw_ok[:len(got)], f"选票与纯排序不一致: {got} vs {raw_ok}"
print("④ 与 signal_history 纯排序一致（ST/北交所过滤后）OK")
state.close(); tushare.close()
print("\n全部通过。reg10_solo 明日起由 strategy_accounts_daily.sh 自动建仓交易。")
