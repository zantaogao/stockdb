"""验证 fusion_dual（三因子+三模型）信号生成：get_signal_targets 单测（信号日 20260810）"""
import sqlite3, sys
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'scripts'))

from scripts.strategy_accounts_daily import get_signal_targets, get_filtered_codes, ts_code
import duckdb

state = sqlite3.connect(str(BASE / 'state.db'))
tushare = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)
bad = get_filtered_codes(tushare)

picks = get_signal_targets(state, tushare, '20260810', 'fusion_dual', bad, top_n=10)
print(f'fusion_dual 强买候选: {len(picks)} 只')
print('Top 10:')
names = {}
for ts, s in tushare.execute("SELECT ts_code, name FROM stock_basic").fetchall():
    names[ts.split('.')[0]] = name if (name := ts and None) else None
name_map = {ts.split('.')[0]: nm for ts, nm in tushare.execute("SELECT ts_code, name FROM stock_basic").fetchall()}
for i, (c, s) in enumerate(picks[:10]):
    print(f'  {i+1}. {c} {name_map.get(c, "")} 组合分{s:.1f}')

# 对比各榜 top10 看交集
print()
for src, label in [('fusion_3f', '三因子'), ('fusion_dual', '三因子+三模型')]:
    p = get_signal_targets(state, tushare, '20260810', src, bad, top_n=10)
    print(f'{label} top10: {[c for c, _ in p[:10]]}')
md = state.execute("""
    SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')='20260810'
    ORDER BY fusion_score DESC LIMIT 10""").fetchall()
print(f'三模型 top10: {[r[0] for r in md]}')
state.close(); tushare.close()
