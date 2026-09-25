"""验证主账户当日收益计算（2026-08-10 面板改动）
场景1: daily 最新==今天（盘后）→ 今日价=今日收盘, 昨收=前一交易日
场景2: daily 最新<今天（盘中/周末）→ 今日价=实时价(fallback昨收), 昨收=最新收盘
"""
import sqlite3, duckdb
from datetime import datetime

TUSHARE_DB_PATH = '/Users/zantao/.hermes/stockdb/tushare.db'
STATE_DB = '/Users/zantao/.hermes/stockdb/state.db'

conn = sqlite3.connect(STATE_DB)
acc = conn.execute("SELECT cash_balance FROM account_balance WHERE account_id='main'").fetchone()
cash = acc[0] if acc else 0
pos_rows = conn.execute("SELECT code, shares, avg_cost, buy_date, latest_price, name FROM holdings").fetchall()
conn.close()

tdb = duckdb.connect(TUSHARE_DB_PATH, read_only=True)
dates = [r[0] for r in tdb.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 2").fetchall()]
print('daily 最近两个交易日:', dates)

closes = {}
for d in dates:
    for ts, c in tdb.execute("SELECT ts_code, close FROM daily WHERE trade_date=?", [d]).fetchall():
        closes.setdefault(ts, {})[d] = float(c)
tdb.close()

today = datetime.now().strftime('%Y%m%d')
print('今天:', today)

import sys
if '--sim-after-close' in sys.argv:
    # 模拟盘后场景：daily 最新交易日 == 今天
    today = dates[0]
    print('(模拟盘后: daily 已更新到今天', today, ')')


# 场景2（当前很可能的状态：盘中/周末，daily 最新<今天）
d1, d2 = dates[0], dates[1]
has_today_close = d1 == today
prev_d = d2 if (has_today_close and len(dates) > 1) else d1
print(f'场景: has_today_close={has_today_close}, 今日价日={d1}, 昨收基准日={prev_d}')

daily_ret, yest_asset = 0.0, cash
detail = []
for r in pos_rows:
    code, shares, avg_cost, buy_date = r[0], r[1] or 0, r[2] or 0, r[3]
    if shares <= 0:
        continue
    full = f"{code}.SH" if code.startswith('6') else f"{code}.SZ"
    cc = closes.get(full, {})
    cur = cc.get(d1)
    prev = cc.get(prev_d)
    if cur is None or prev is None:
        detail.append((code, r[5], '跳过(无收盘)'))
        continue
    today_bought = str(buy_date or '').replace('-', '') == today
    base = avg_cost if today_bought else prev
    gain = shares * (cur - base)
    daily_ret += gain
    if not today_bought:
        yest_asset += shares * prev
    detail.append((code, r[5], shares, prev, cur, round(gain, 2), '今买' if today_bought else ''))

print(f'\n当日收益金额: {daily_ret:,.2f}')
print(f'昨日总资产: {yest_asset:,.2f}')
print(f'当日收益率: {daily_ret / yest_asset * 100:.2f}%' if yest_asset > 0 else 'N/A')
print('\n明细(代码 名称 股数 昨收 今日价 收益 标记):')
for d in detail:
    print(' ', d)
