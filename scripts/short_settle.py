#!/usr/bin/env python3
"""
短线盘后结算 v1 — 每日收盘后运行
- 生成短线日报
- 清理过期观察
- 计算当日盈亏
"""
import os, sys, json, duckdb, numpy as np
from datetime import datetime, date, timedelta
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
SHORT_HOLD_PATH = BASE / 'short_holdings.json'
SHORT_ACCT_PATH = BASE / 'short_account.json'
SHORT_LOG_PATH = BASE / 'short_trade_log.json'
DB_PATH = BASE / 'stock.db'

def load_json(path, default=None):
    if default is None: default = {}
    try: return json.loads(open(path).read())
    except: return default

def main():
    today = date.today().isoformat()
    print("="*55)
    print(f"📋 短线盘后结算 — {today}")
    print("="*55)

    sh = load_json(SHORT_HOLD_PATH, {"short_positions": [], "short_watch": [], "initial_capital": 500000})
    acct = load_json(SHORT_ACCT_PATH, {"cash": 500000})
    conn = duckdb.connect(str(DB_PATH), read_only=True)

    positions = sh.get('short_positions', [])
    watches = sh.get('short_watch', [])
    cash = acct.get('cash', 500000)
    initial = sh.get('initial_capital', 500000)

    # 查询当日收盘价
    latest_date = conn.execute("SELECT MAX(date) FROM stock_daily WHERE stock_code IN (SELECT '000001')").fetchone()[0]
    # 获取所有持仓+观察的最新价
    all_codes = list(set([p['code'] for p in positions] + [w['code'] for w in watches]))

    prices = {}
    for code in all_codes:
        r = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}'
            ORDER BY date DESC LIMIT 1
        """).fetchone()
        if r:
            prices[code] = float(r[0])

    # ── 持仓估值 ──
    total_value = cash
    print(f"\n💰 持仓 ({len(positions)} 只):")
    pos_value = 0
    for p in positions:
        code = p['code']
        cur = prices.get(code, p['buy_price'])
        cost = p['buy_price']
        pnl = (cur / cost - 1) * 100
        val = p['shares'] * cur
        pos_value += val
        total_value += val
        icon = '🟢' if pnl >= 0 else '🔴'
        print(f"  {icon} {code} {p['name']:8s} {p['shares']}股  "
              f"成本{cost:.2f}→现{cur:.2f} 盈亏{pnl:+.1f}% 市值{val:,.0f}")

    total_pnl = (total_value / initial - 1) * 100
    hit = sum(1 for p in positions if prices.get(p['code'], p['buy_price']) > p['buy_price'])
    hit_rate = round(hit / max(len(positions), 1) * 100, 1)
    print(f"\n  总资产: {total_value:,.0f}  (现金{cash:,.0f} + 市值{pos_value:,.0f})")
    print(f"  总盈亏: {total_pnl:+.2f}%  持仓命中率: {hit_rate}%")

    # ── 观察池 ──
    print(f"\n👀 观察池 ({len(watches)} 只):")
    for w in sorted(watches, key=lambda x: x.get('signal_score', 0), reverse=True)[:10]:
        cur = prices.get(w['code'], w['price'])
        dev = (cur/w['price']-1)*100 if w['price'] else 0
        print(f"  {w['code']} {w['name']:8s} {w.get('style',''):12s} "
              f"评分{w.get('signal_score',0):.0f}  现{cur:.2f} 区间{w.get('entry_low','')}~{w.get('entry_high','')}")

    # ── 今日交易 ──
    log = load_json(SHORT_LOG_PATH, [])
    today_trades = [t for t in log if t.get('time','').startswith(today)]
    if today_trades:
        print(f"\n📝 今日交易 ({len(today_trades)} 笔):")
        for t in today_trades:
            print(f"  {t['type']} {t.get('code','')} {t.get('shares','')}股@{t.get('price','')} "
                  f"{' | '.join(t.get('reason','').split(' | ')[:2])}")

    # ── 清理过期观察（超过3天无触发） ──
    before = len(watches)
    watches = [w for w in watches
               if (date.today() - datetime.strptime(w['add_date'], '%Y-%m-%d').date()).days <= 3]
    cleared = before - len(watches)

    # 删除已持仓观察
    pos_codes = {p['code'] for p in positions}
    watches = [w for w in watches if w['code'] not in pos_codes]

    sh['short_positions'] = positions
    sh['short_watch'] = watches
    with open(SHORT_HOLD_PATH, 'w') as f:
        json.dump(sh, f, ensure_ascii=False, indent=2)

    acct['cash'] = cash
    nav = {'date': today, 'total_value': round(total_value, 2), 'cash': round(cash, 2),
           'positions_value': round(pos_value, 2), 'total_pnl': round(total_pnl, 2)}
    acct.setdefault('nav_history', []).append(nav)
    acct['updated_at'] = today
    with open(SHORT_ACCT_PATH, 'w') as f:
        json.dump(acct, f, ensure_ascii=False, indent=2)

    print(f"\n  清理过期观察: {cleared} 只")
    print(f"🏁 完成")

    conn.close()

if __name__ == '__main__':
    main()
