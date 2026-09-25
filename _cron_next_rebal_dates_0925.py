# 按生产口径实算各账户下次重评日（09-25 核查策略新鲜度）
# 口径=strategy_accounts_daily.py 684-717: 数 daily 表里 > last_re 的交易日数 n，n>=窗口 即重评日
import json, sqlite3, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
import duckdb
t = duckdb.connect('tushare.db', read_only=True)
tds = [r[0] for r in t.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
t.close()
s = sqlite3.connect('ledger.db')
meta = {a: str(json.loads(cfg or '{}').get('last_rebalance_date') or '').replace('-','')
        for a, cfg in s.execute("SELECT account_id, config_json FROM strategy_accounts_meta")}
win = {'cmmr':10, 'cmmr_clf':10, 'reg10_solo':10, 'cmmr_fusion':20, 'fusion_center':20, 'center_dual':20}
today = '20260925'  # 今日（若 daily 已有 0925 盘中数据则含）
for aid, w in win.items():
    lrd = meta[aid]
    future = [d for d in tds if d > lrd]
    # 重评发生在第 w 个交易日盘中（盘中判定用 < 今日 修正过：n = count(> lrd, <= 今日)）
    n = sum(1 for d in future if d <= today)
    # 下次重评日 = future 列表第 w 个（索引 w-1），若不足则 None
    next_re = future[w-1] if len(future) >= w else None
    # 注意：重评日当天账户会重建并把 lrd 推到当天，所以从当前 lrd 起算
    print(f"{aid:14s} 窗口{w:2d}日 lrd={lrd} 已过{n}个交易日 下次重评日={next_re}")
