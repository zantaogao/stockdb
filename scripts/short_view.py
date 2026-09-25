#!/usr/bin/env python3
"""快捷查看短线账户 — 用法: python3 ~/.hermes/stockdb/scripts/short_view.py"""
import json, os, urllib.request
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
acct = json.loads((BASE / 'short_account.json').read_text())
hold = json.loads((BASE / 'short_holdings.json').read_text())
trades = json.loads((BASE / 'short_trade_log.json').read_text()) if (BASE / 'short_trade_log.json').exists() else []

cash = acct.get('cash', 0)
initial = hold.get('initial_capital', 500000)
positions = hold.get('short_positions', [])
watches = hold.get('short_watch', [])
nav = acct.get('nav_history', [])
last_nav = nav[-1] if nav else {}

# 获取实时行情计算命中率
prices = {}
if positions:
    codes = [p['code'] for p in positions]
    batch = ','.join(f'sh{p["code"]}' if p['code'].startswith(('6','68')) else f'sz{p["code"]}' for p in positions)
    try:
        req = urllib.request.Request(f'https://hq.sinajs.cn/list={batch}', headers={'Referer':'https://finance.sina.com.cn'})
        raw = urllib.request.urlopen(req, timeout=5).read().decode('gbk')
        for line in raw.strip().split(';\n'):
            if '=' not in line: continue
            k = line.split('=')[0].split('_')[-1]
            code = k[2:] if len(k) > 2 and k[:2] in ('sh','sz') else k
            d = line.split('\"')[1].split(',')
            if len(d) < 3: continue
            prices[code] = float(d[3]) if d[3] else 0
    except:
        pass

hit = sum(1 for p in positions if prices.get(p['code'], p['buy_price']) > p['buy_price'])
hit_rate = round(hit / max(len(positions), 1) * 100, 1)

print('='*55)
print('📊 短线账户')
print('='*55)
print(f'  初始资金: {initial:>8,.0f}   现金: {cash:>10,.0f}')
if last_nav:
    print(f'  总资产:   {last_nav.get("total_value",cash):>8,.0f}   总盈亏: {last_nav.get("total_pnl",0):>+7.2f}%  持仓命中率: {hit_rate}%')
else:
    print(f'  总资产:   {cash:>8,.0f}   总盈亏:  +0.00%  持仓命中率: N/A')

# 持仓
print(f'\n📋 持仓 ({len(positions)} 只):')
if positions:
    for p in positions:
        pr = prices.get(p['code'], p['buy_price'])
        pnl = (pr/p['buy_price'] - 1)*100
        icon = '🟢' if pnl >= 0 else '🔴'
        print(f'  {icon} {p["code"]} {p["name"]:8s} {p.get("style",""):12s} '
              f'{p["shares"]:>4}股  成本{p["buy_price"]:>8.2f}→现{pr:.2f} 盈亏{pnl:+.1f}%  '
              f'止损{p.get("stop_loss",0):>8.2f}  目标{p.get("target",0):>8.2f}')
else:
    print('  (空)')

# 观察池  
print(f'\n👀 观察池 ({len(watches)} 只):')
if watches:
    for w in sorted(watches, key=lambda x: x.get('signal_score',0), reverse=True):
        print(f'  {w["code"]} {w["name"]:8s} {w.get("style",""):12s} '
              f'评分{w.get("signal_score",0):>3.0f}  区间{w.get("entry_low",0):>8.2f}~{w.get("entry_high",0):.2f}')
else:
    print('  (空)')

# 今日交易
print(f'\n📝 今日交易 ({len([t for t in trades if t.get("time","").startswith(os.popen("date +%Y-%m-%d").read().strip())])} 笔):')
today = os.popen('date +%Y-%m-%d').read().strip()
today_trades = [t for t in trades if t.get('time','').startswith(today)]
if today_trades:
    for t in today_trades:
        print(f'  {t["type"]:10s} {t.get("code","")} {t.get("shares",0)}股@{t.get("price",0)} '
              f'{" | ".join(t.get("reason","").split(" | ")[:2])}')
else:
    print('  (无)')
