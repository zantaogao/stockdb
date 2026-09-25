#!/usr/bin/env python3
"""2026-09-16 收盘后用户指令：手动卖出全部碎仓（含M2，M2另跑）。
口径=系统既有 DUST_CLEAN_RATIO：持仓市值 < 账户NAV×1%。
主账户走 holdings/account_balance/trade_log；策略账户走 strategy_positions/meta/trade_log。
现价取今日收盘（盘后新浪实时值=收盘价）。只跑一次，幂等：已进 trade_log(今日,碎仓清理) 的票跳过。"""
import sqlite3, urllib.request, datetime, sys

DB = '/Users/zantao/.hermes/stockdb/ledger.db'
TODAY = '20260916'
NOW = datetime.datetime.now().isoformat(timespec='seconds')
RATIO = 0.01

def sina(codes):
    syms = []
    for code in codes:
        p = 'sh' if code[0] == '6' else ('bj' if code[0] in '49' else 'sz')
        syms.append(p + code)
    req = urllib.request.Request('https://hq.sinajs.cn/list=' + ','.join(syms),
                                 headers={'Referer': 'https://finance.sina.com.cn'})
    txt = urllib.request.urlopen(req, timeout=15).read().decode('gbk')
    out = {}
    for line in txt.strip().split('\n'):
        try:
            var, data = line.split('=', 1)
            code = var.split('_')[-1][2:]
            f = data.strip('";').split(',')
            px = float(f[3]) or float(f[2])
            if px > 0:
                out[code] = px
        except Exception:
            pass
    return out

c = sqlite3.connect(DB)

def already_sold(aid):
    return {r[0] for r in c.execute(
        "SELECT code FROM trade_log WHERE trade_date=? AND strategy=? AND notes LIKE '手动碎仓清理%'",
        (TODAY, aid)).fetchall()}

def log_trade(aid, code, name, px, shares, amount, pnl_yuan, pnl_pct):
    c.execute("""INSERT INTO trade_log
        (code,name,direction,price,quantity,amount,trade_date,trade_time,strategy,signal_score,notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (code, name, 'SELL', round(px, 3), shares, round(amount, 2), TODAY, NOW, aid,
         None, f'手动碎仓清理 盈亏{pnl_yuan:+,.0f}元 ({pnl_pct:+.2f}%)'))

total_sold, total_amt = 0, 0.0

# ── 主账户 ──
sold = already_sold('main')
hold = c.execute("SELECT code,name,shares,avg_cost FROM holdings").fetchall()
cash = c.execute("SELECT cash_balance FROM account_balance").fetchone()[0]
px_map = sina(sorted({h[0] for h in hold}))
nav = cash + sum(h[2] * px_map.get(h[0], h[3]) for h in hold)
thr = nav * RATIO
for code, name, shares, cost in hold:
    if code in sold or code not in px_map:
        continue
    px = px_map[code]
    amt = shares * px
    if amt >= thr:
        continue
    log_trade('main', code, name, px, shares, amt, shares * (px - cost), (px / cost - 1) * 100)
    c.execute("DELETE FROM holdings WHERE code=?", (code,))
    cash += amt
    total_sold += 1; total_amt += amt
    print(f'[main] 卖 {code} {name} {shares}股 @{px:.2f} = {amt:,.0f}元 盈亏{(px/cost-1)*100:+.1f}%')
nav_all = cash + sum(h[2] * px_map.get(h[0], h[3]) for h in hold
                     if not c.execute("SELECT 1 FROM holdings WHERE code=?", (h[0],)).fetchone()) + \
          sum(r[0] * px_map.get(r[1], 0) for r in [])
c.execute("UPDATE account_balance SET cash_balance=?, total_value=?, last_update=?",
          (cash, cash + sum(h[2] * px_map.get(h[0], h[3])
                            for h in c.execute("SELECT code,name,shares,avg_cost FROM holdings")), NOW))

# ── 策略账户 ──
for aid in [r[0] for r in c.execute("SELECT account_id FROM strategy_accounts_meta").fetchall()]:
    sold = already_sold(aid)
    pos = c.execute("SELECT code,name,shares,avg_cost FROM strategy_positions WHERE account_id=?", (aid,)).fetchall()
    acct_cash = c.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id=?", (aid,)).fetchone()[0]
    if not pos:
        continue
    pm = sina(sorted({p[0] for p in pos}))
    nav = float(acct_cash) + sum(p[2] * pm.get(p[0], p[3]) for p in pos)
    thr = nav * RATIO
    for code, name, shares, cost in pos:
        if code in sold or code not in pm:
            continue
        px = pm[code]
        amt = shares * px
        if amt >= thr:
            continue
        log_trade(aid, code, name, px, shares, amt, shares * (px - cost), (px / cost - 1) * 100)
        c.execute("DELETE FROM strategy_positions WHERE account_id=? AND code=?", (aid, code))
        acct_cash = float(acct_cash) + amt
        total_sold += 1; total_amt += amt
        print(f'[{aid}] 卖 {code} {name} {shares}股 @{px:.2f} = {amt:,.0f}元 盈亏{(px/cost-1)*100:+.1f}%')
    c.execute("UPDATE strategy_accounts_meta SET cash=?, updated_at=? WHERE account_id=?", (acct_cash, NOW, aid))

c.commit()
print(f'DONE 共卖{total_sold}笔 回收{total_amt:,.0f}元')
