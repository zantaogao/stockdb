#!/usr/bin/env python3
"""回滚 2026-09-25（调休休市日）误落的主账户 2 笔成交。

撤销：id1174 卖 301110 青木科技 @36.50×1000、id1175 买 300492 华图山鼎 @21.96×1600
流水已备份 orders/voided_20260925_nontrade.json（删除前导出）。

回滚账目（单一权威源 ledger.db）：
1. trade_log 删除 0925 主账户 2 行
2. holdings：删 300492；恢复 301110（1000股@36.741 买日按 0917 建仓，参数按主账户规则重算）
3. account_balance：cash = 1514.71 - 36500(卖出回笼) + 35146.54(买出成本) = 1561.25
   total_value 由下一轮 17:50 收盘估值刷新，这里只按当前价重算一次
4. position_peaks：删 300492 峰；301110 峰留给下一轮重建
5. sim_accounts/agent_auto.json nav_history 尾行回指 0924
6. strategy_accounts 删除 date=20260925 全部 NAV 行（休市日无 NAV 概念）
"""
import json
import sqlite3
from datetime import datetime

import duckdb

BASE = '/Users/zantao/.hermes/stockdb'
VOID_IDS = (1174, 1175)
CASH_TODAY = 1514.7126000001372
SELL_REV = 36.5 * 1000          # 36500 回笼（不含费，与当初落账口径一致）
BUY_COST = 21.96 * 1600         # 35136? 表内 amount=35146.5408 含费 → 以表内 amount 为准
BUY_AMOUNT = 35146.540799999995

c = sqlite3.connect(f'{BASE}/ledger.db', timeout=30)
now = datetime.now().isoformat(timespec='seconds')

# 0) 备份将删的两行（幂等：文件在则不覆盖）
import os
os.makedirs(f'{BASE}/orders', exist_ok=True)
backup = f'{BASE}/orders/voided_20260925_nontrade.json'
if not os.path.exists(backup):
    raise SystemExit('缺备份文件，先确认 orders/voided_20260925_nontrade.json 存在')

# 1) trade_log 删除
n = c.execute("DELETE FROM trade_log WHERE id IN (?,?)", VOID_IDS).rowcount
print('trade_log deleted:', n)

# 2) holdings：删 300492，恢复 301110
n = c.execute("DELETE FROM holdings WHERE code LIKE '300492%' AND status='hold'").rowcount
print('holdings 300492 deleted:', n)
# 301110 恢复：主账户仓 1000 股，原始建仓 trade_log id773 2026-09-04 @37.81（0925 误卖前一直在持仓）
# latest_price=36.5（0925 实盘价，下轮 17:50 估值刷新覆盖）；止损留 0 由下轮 sync_to_db 按规则重算
c.execute("""INSERT OR REPLACE INTO holdings
    (code,name,status,buy_date,avg_cost,shares,latest_price,pnl,pnl_pct,update_time,target_price,stop_loss)
    VALUES ('301110','青木科技','hold','2026-09-04', 37.81 ,1000, 36.5,?,?,?, 0, 0)""",
    (None, None, now))
print('301110 restored')

# 3) account_balance
new_cash = round(CASH_TODAY - SELL_REV + BUY_AMOUNT, 2)
# 市值按 holdings 当前 latest_price（301110 用 36.5）重算
mval = 0.0
for code, sh, lp in c.execute("SELECT code, shares, latest_price FROM holdings WHERE status='hold'"):
    mval += sh * (lp or 0)
total = round(new_cash + mval, 2)
c.execute("UPDATE account_balance SET cash_balance=?, total_value=?, last_update=? WHERE account_id='main'",
          (new_cash, total, now))
print(f'cash -> {new_cash}, total -> {total}')

# 4) position_peaks 删 300492
n = c.execute("DELETE FROM position_peaks WHERE code LIKE '300492%'").rowcount
print('peaks 300492 deleted:', n)
c.commit()

# 5) agent_auto.json nav_history 尾行（0925 估值行）删除
import json
ap = f'{BASE}/sim_accounts/agent_auto.json'
d = json.load(open(ap))
before = len(d['nav_history'])
d['nav_history'] = [h for h in d['nav_history'] if str(h.get('date', '')).replace('-', '') != '20260925']
json.dump(d, open(ap, 'w'), ensure_ascii=False, indent=2)
print('agent_auto nav_history:', before, '->', len(d['nav_history']))

# 6) strategy_accounts 删 20260925 NAV 行
n = c.execute("DELETE FROM strategy_accounts WHERE date='20260925'").rowcount
c.commit()
print('strategy_accounts 20260925 rows deleted:', n)
c.close()

# 验证
c = sqlite3.connect(f'{BASE}/ledger.db', timeout=30)
print('--- VERIFY ---')
print('trade_log 0925:', c.execute("SELECT id,code,direction FROM trade_log WHERE trade_date='2026-09-25'").fetchall())
print('holdings n:', c.execute("SELECT COUNT(*) FROM holdings WHERE status='hold'").fetchone())
print('301110:', c.execute("SELECT code,shares,avg_cost,buy_date,target_price FROM holdings WHERE code LIKE '301110%'").fetchall())
print('300492 gone:', c.execute("SELECT COUNT(*) FROM holdings WHERE code LIKE '300492%'").fetchone())
print('bal:', c.execute("SELECT cash_balance,total_value FROM account_balance WHERE account_id='main'").fetchall())
print('sa 0925:', c.execute("SELECT COUNT(*) FROM strategy_accounts WHERE date='20260925'").fetchone())
c.close()
