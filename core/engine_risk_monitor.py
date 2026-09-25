"""
新引擎盘中风险监控 — sim_accounts/sim.json
=========================================
每10分钟巡检一次，触发止损立即卖出

止损规则:
  - 硬止损: -8%（主板）/ -12%（创业板/科创板）
  - 高位回落: 盈利>5%后从峰值回落>8%
"""
import json, sys, time, os
from datetime import datetime
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
SIM_PATH = BASE / 'sim_accounts' / 'sim.json'
LOG_PATH = BASE / 'engine_risk_log.json'


def fetch_price(code):
    """从新浪获取实时价格"""
    prefix = 'sz' if code.startswith(('0','3','001')) else 'sh'
    for attempt in range(2):
        try:
            import urllib.request
            url = f'https://hq.sinajs.cn/list={prefix}{code}'
            req = urllib.request.Request(url, headers={'Referer':'https://finance.sina.com.cn'})
            resp = urllib.request.urlopen(req, timeout=5)
            text = resp.read().decode('gbk')
            if '"' in text:
                raw = text.split('"')[1].split(',')
                if len(raw) > 3 and raw[3]:
                    return float(raw[3])
        except Exception:
            time.sleep(1)
    return None


def main():
    if not SIM_PATH.exists():
        return

    sys.path.insert(0, str(BASE))
    from core.unified_account import AccountStore

    store = AccountStore()
    acct = store.load("sim")
    if not acct.positions:
        return

    now = datetime.now()
    print(f"\n🛡️ 新引擎风险巡检 — {now.strftime('%H:%M')}")
    print(f"  持仓 {len(acct.positions)} 只")

    sells = []
    for pos in list(acct.positions):
        code = pos.code
        cost = pos.avg_cost
        shares = pos.shares
        if shares <= 0:
            continue

        price = fetch_price(code)
        if not price:
            print(f"  ⚠️ {code} {pos.name} 获取价格失败")
            continue

        pnl = round((price / cost - 1) * 100, 2)
        peak = pos.peak_price or cost
        if price > peak:
            pos.peak_price = price
            peak = price
        drawdown = round((peak - price) / peak * 100, 2) if peak > 0 else 0
        board = 'gem' if code.startswith(('300','301','688','689')) else 'main'
        hard_stop = -12.0 if board == 'gem' else -8.0

        reasons = []
        if pnl <= hard_stop:
            reasons.append(f"硬止损({pnl:.1f}%)")
        if pnl > 5 and drawdown >= 8.0:
            reasons.append(f"高位回落{drawdown:.1f}%")

        if reasons:
            reason = '; '.join(reasons)
            exec_price = price * 0.995  # 卖出滑点
            amount = exec_price * shares
            pnl_exec = round((exec_price / cost - 1) * 100, 2)
            acct.cash += amount
            pos.shares -= shares
            acct.trades.append(__import__('datetime').datetime.now())
            from core.unified_account import Trade
            acct.trades.append(Trade(
                date=datetime.now().strftime("%Y-%m-%d %H:%M"),
                action="卖出", code=code, name=pos.name,
                price=exec_price, shares=shares, amount=amount,
                pnl_pct=pnl_exec, reason=reason,
            ))
            if pos.shares <= 0:
                acct.remove_position(code)
            store.save(acct)
            sells.append(f"{code} {pos.name} PnL{pnl_exec:+.1f}% {reason}")
            print(f"  🔴 卖出 {code} {pos.name} PnL{pnl_exec:+.1f}% {reason}")

    if sells:
        print(f"\n⚠️ 执行 {len(sells)} 笔卖出")
        for s in sells:
            print(f"  {s}")
    else:
        print(f"  ✅ 正常")


if __name__ == '__main__':
    main()
