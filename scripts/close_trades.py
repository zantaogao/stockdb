#!/usr/bin/env python3
"""
盘后平仓建议 — 收盘后运行 (15:30)
只推送建议，不自动平仓。用户通过 Web 面板确认后才写入 holdings.json。
"""

import os, sys, json, urllib.request
from datetime import datetime

for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

HOLD_PATH = os.path.expanduser('~/.hermes/stockdb/holdings.json')
DB = os.path.expanduser('~/.hermes/stockdb/stock.db')
TODAY = datetime.now().strftime('%Y-%m-%d')

def sina_code(code):
    if code in ('000001', '399001', '399006'):
        return {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}[code]
    return f'sh{code}' if code.startswith(('6','68')) else f'sz{code}'

def fetch_quote(symbol):
    try:
        url = f"https://hq.sinajs.cn/list={symbol}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=5).read()
        text = raw.decode('gbk')
        if '=""' in text: return None
        parts = text.split('"')[1].split(',')
        if len(parts) < 10: return None
        return {
            'name': parts[0], 'price': float(parts[3]),
            'high': float(parts[4]), 'low': float(parts[5]),
            'prev_close': float(parts[2]),
        }
    except:
        return None

def main():
    if datetime.now().weekday() >= 5:
        return

    try:
        with open(HOLD_PATH, encoding='utf-8') as f:
            data = json.load(f)
    except:
        return

    positions = data.get('positions', [])
    suggestions = []

    # 先用Sina实时价，失败则用DB前日收盘
    import duckdb
    conn = duckdb.connect(DB, read_only=True)

    for pos in positions:
        if pos.get('status') != 'hold':
            continue

        code = pos['code']
        name = pos.get('name', code)
        bp = pos.get('buy_price')
        sl = pos.get('stop_loss')
        tg = pos.get('target')

        if not bp:
            continue

        # 拉价格
        q = fetch_quote(sina_code(code))
        if q:
            price = q['price']
        else:
            r = conn.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 1").fetchone()
            if not r: continue
            price = float(r[0])

        pnl = (price - bp) / bp * 100
        held_days = 0
        if pos.get('buy_date'):
            try:
                held_days = (datetime.now() - datetime.strptime(str(pos['buy_date']), '%Y-%m-%d')).days
            except: pass

        signal = None
        if sl and price <= sl:
            signal = f"🚨 跌破止损 {sl}（现价{price:.2f} 浮亏{pnl:+.1f}%）"
        elif tg and price >= tg:
            signal = f"🎯 达到目标 {tg}（现价{price:.2f} 浮盈{pnl:+.1f}%）"
        elif sl and price <= sl * 1.03:
            signal = f"⚡ 逼近止损 {sl}（现价{price:.2f} 距止损{(price-sl)/sl*100:.1f}%）"
        elif held_days >= 8 and abs(pnl) < 5:
            signal = f"⏰ 持有{held_days}天未动（{pnl:+.1f}%）— 考虑换股"

        if signal:
            suggestions.append({
                'code': code, 'name': name,
                'price': price, 'pnl': round(pnl, 2),
                'signal': signal, 'held_days': held_days,
            })

    conn.close()

    if suggestions:
        print(f"📋 平仓建议 ({TODAY})")
        print('─' * 50)
        for s in suggestions:
            emoji = '🟢' if s['pnl'] > 0 else '🔴'
            print(f"  {emoji} {s['name']}({s['code']}) 现价{s['price']:.2f} 盈亏{s['pnl']:+.1f}% 持有{s['held_days']}天")
            print(f"     {s['signal']}")
        print(f"\n  💡 打开 http://localhost:8090 → 卖出 确认平仓")
    # 无建议则静默

if __name__ == '__main__':
    main()
