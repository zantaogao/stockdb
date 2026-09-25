#!/usr/bin/env python3
"""Pre-market briefing generator - reads all data from stock.db in one pass."""

import json
import duckdb
import datetime
import sys

STOCKDB = '/Users/zantao/.hermes/stockdb'
DB_PATH = f'{STOCKDB}/stock.db'

# ── 1. Load holdings ──
with open(f'{STOCKDB}/holdings.json') as f:
    holdings = json.load(f)

holds = [p for p in holdings['positions'] if p.get('status') == 'hold']
watch_active = [p for p in holdings['positions'] if p.get('status') == 'watch_active']
watch = [p for p in holdings['positions'] if p.get('status') == 'watch']
watch_cold = [p for p in holdings['positions'] if p.get('status') == 'watch_cold']
all_relevant = holds + watch_active + watch + watch_cold
codes = [p['code'] for p in all_relevant]

# ── 2. Connect DB once ──
con = duckdb.connect(DB_PATH)

latest_stock_date = con.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
ref_date = latest_stock_date

# ── 3. Index data ──
idx = con.execute(f"""
    SELECT index_code, date, open, close, high, low, change_pct, amount
    FROM index_daily
    WHERE index_code IN ('000001','399001') AND date = '{ref_date}'
    ORDER BY index_code
""").fetchall()

sh_data = con.execute(f"""
    SELECT date, close FROM index_daily 
    WHERE index_code='000001' ORDER BY date DESC LIMIT 60
""").fetchall()

sh_latest = sh_data[0][1]
recent_sh = [r[1] for r in reversed(sh_data[:60])]
sh_ma20 = sum(recent_sh[-20:]) / 20 if len(recent_sh) >= 20 else None
sh_ma60 = sum(recent_sh) / 60 if len(recent_sh) >= 60 else None
sh_5ago = sh_data[4][1] if len(sh_data) >= 5 else None
sh_20ago = sh_data[19][1] if len(sh_data) >= 20 else None

north = con.execute(f"""
    SELECT date, sh_net, sz_net, total_net FROM north_flow
    ORDER BY date DESC LIMIT 5
""").fetchall()

# ── 4. Holdings stock data ──
codes_str = ','.join(f"'{c}'" for c in codes) if codes else ''
stock_data = {}
mf_rows = []
if codes:
    rows = con.execute(f"""
        SELECT stock_code, date, open, close, high, low, volume, amount, change_pct, turn_rate
        FROM stock_daily
        WHERE stock_code IN ({codes_str})
          AND date >= '{ref_date}'::DATE - INTERVAL '90 days'
        ORDER BY stock_code, date DESC
    """).fetchall()
    for r in rows:
        sc = r[0]
        if sc not in stock_data:
            stock_data[sc] = []
        stock_data[sc].append({
            'date': r[1], 'open': r[2], 'close': r[3], 'high': r[4], 'low': r[5],
            'volume': r[6], 'amount': r[7], 'change_pct': r[8], 'turn_rate': r[9]
        })

    mf_rows = con.execute(f"""
        SELECT stock_code, date, main_net, main_pct
        FROM money_flow
        WHERE stock_code IN ({codes_str})
        ORDER BY stock_code, date DESC
    """).fetchall()

# ── 5. Hot sectors (market-wide) ──
hot_sectors = con.execute(f"""
    SELECT s.industry, COUNT(*) as cnt, ROUND(AVG(d.change_pct), 2) as avg_chg
    FROM stock_daily d
    JOIN stock_info s ON d.stock_code = s.stock_code
    WHERE d.date = '{ref_date}' AND s.industry IS NOT NULL
    GROUP BY s.industry
    HAVING cnt >= 5
    ORDER BY avg_chg DESC
    LIMIT 5
""").fetchall()

con.close()

# ── 6. Compute indicators ──
mf_data = {}
for r in mf_rows:
    sc = r[0]
    if sc not in mf_data:
        mf_data[sc] = {'main_net': r[2], 'main_pct': r[3], 'date': r[1]}

def compute_ma(prices, period):
    if len(prices) >= period:
        return sum(prices[-period:]) / period
    return None

stock_indicators = {}
for sc, data in stock_data.items():
    if not data:
        continue
    data_sorted = sorted(data, key=lambda x: x['date'])
    closes = [d['close'] for d in data_sorted]
    latest = data_sorted[-1]
    n = len(closes)

    chg5 = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else None
    chg20 = (closes[-1] / closes[-20] - 1) * 100 if n >= 20 else None
    chg60 = (closes[-1] / closes[0] - 1) * 100 if n >= 60 else None

    ma5 = compute_ma(closes, 5)
    ma10 = compute_ma(closes, 10)
    ma20 = compute_ma(closes, 20)
    ma60 = compute_ma(closes, 60)

    dev5 = (latest['close'] / ma5 - 1) * 100 if ma5 else None
    dev20 = (latest['close'] / ma20 - 1) * 100 if ma20 else None
    dev60 = (latest['close'] / ma60 - 1) * 100 if ma60 else None

    avg_vol = sum(d['volume'] for d in data_sorted[-6:-1]) / 5 if n >= 6 else 0
    vol_ratio = latest['volume'] / avg_vol if avg_vol > 0 else None

    mf = mf_data.get(sc, {})
    stock_indicators[sc] = {
        'close': latest['close'], 'change_pct': latest['change_pct'],
        'chg5': chg5, 'chg20': chg20, 'chg60': chg60,
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'dev5': dev5, 'dev20': dev20, 'dev60': dev60,
        'vol_ratio': vol_ratio, 'turn_rate': latest['turn_rate'],
        'main_net': mf.get('main_net'), 'main_pct': mf.get('main_pct'),
    }

def ma_status_line(si):
    c = si['close']
    above = []
    for k in ['MA5','MA10','MA20','MA60']:
        mk = k.lower()
        if si.get(mk) and c > si[mk]:
            above.append(k)
    if len(above) >= 3:
        return '📈 强势(站上' + '/'.join(above[:3]) + '...)'
    elif len(above) == 0:
        away = []
        for k in ['MA5','MA10','MA20','MA60']:
            mk = k.lower()
            if si.get(mk):
                dev = (c / si[mk] - 1) * 100
                away.append(f'{k}({dev:.1f}%)')
        if away:
            return f'📉 弱势(全均线下: {", ".join(away[:2])})'
        return '📉 弱势'
    else:
        devs = []
        for k in ['MA5','MA10','MA20','MA60']:
            mk = k.lower()
            if si.get(mk):
                dev = (c / si[mk] - 1) * 100
                devs.append(f'{k}({dev:+.1f}%)')
        return f'⚡ 震荡({", ".join(devs[:3])})'

def format_pnl(h):
    bp = h.get('buy_price')
    si = stock_indicators.get(h['code'])
    if bp and si:
        return (si['close'] / bp - 1) * 100
    return None

# ════════════════════════════════
# OUTPUT
# ════════════════════════════════

today_str = ref_date.strftime('%Y-%m-%d')
weekday_names = ['周一','周二','周三','周四','周五','周六','周日']
weekday = weekday_names[ref_date.weekday()]

print(f"📊 盘前简报 | {today_str} {weekday}")
print(f"{'='*60}")
print()

# ── 一、大盘状态 ──
print("一、大盘状态")
print("-" * 50)

sh_close = sz_close = sh_chg = sz_chg = sh_amt = None
for i in idx:
    if i[0] == '000001':
        sh_close, sh_chg, sh_amt = i[3], i[6], i[7]
    else:
        sz_close, sz_chg = i[3], i[6]

sh_chg_5d = (sh_latest/sh_5ago - 1)*100 if sh_5ago else None
sh_chg_20d = (sh_latest/sh_20ago - 1)*100 if sh_20ago else None
sh_dev20 = (sh_latest/sh_ma20 - 1)*100 if sh_ma20 else None
sh_dev60 = (sh_latest/sh_ma60 - 1)*100 if sh_ma60 else None

print(f"  上证 {sh_close:.1f}  ({sh_chg:+.2f}%)   深证 {sz_close:.1f}  ({sz_chg:+.2f}%)")
print(f"  近5日: {sh_chg_5d:+.2f}%  近20日: {sh_chg_20d:+.2f}%  MA20: {sh_ma20:.0f}({sh_dev20:+.1f}%)")

# Trend assessment
above_ma20 = sh_latest > sh_ma20 if sh_ma20 else None
above_ma60 = sh_latest > sh_ma60 if sh_ma60 else None
if above_ma20 and above_ma60:
    trend = "短中期偏多 ✅"
elif above_ma20 and not above_ma60:
    trend = "短线反弹中(MA60下方)"
elif not above_ma20 and above_ma60:
    trend = "中期偏多短线调整"
else:
    trend = f"短中期偏弱 ⚠️(MA60下{abs(sh_dev60):.1f}%)"

print(f"  趋势: {trend}")

# Amount
if sh_amt:
    print(f"  成交额: {sh_amt/1e8:.0f}亿")

# North flow (only if within 5 trading days)
if north:
    ln = north[0]
    nd = ln[0]
    nd_str = nd.strftime('%Y-%m-%d') if hasattr(nd, 'strftime') else str(nd)
    days_ago = (latest_stock_date - nd).days if hasattr(latest_stock_date, '__sub__') else 99
    if days_ago <= 10:
        total_net = ln[3] if len(ln) > 3 and ln[3] is not None else (ln[1] or 0) + (ln[2] or 0)
        print(f"  北向资金: {total_net/1e8:+.1f}亿 ({nd_str})")

# Hot sectors
if hot_sectors:
    top3 = hot_sectors[:3]
    sec_strs = [f"{s[0]}(均{s[2]:+.1f}%)" for s in top3 if s[2] >= -0.5]
    if sec_strs:
        print(f"  领涨板块: {' '.join(sec_strs)}")

print()

# ── 二、持仓状态 ──
print("二、持仓状态")
print("-" * 50)

if not holds:
    print("  当前无持仓")
else:
    for h in holds:
        sc, name = h['code'], h.get('name', '?')
        si = stock_indicators.get(sc)
        if not si:
            print(f"  {name}({sc}) — 数据缺失")
            continue
        pnl = format_pnl(h)
        stop = h.get('stop_loss')
        target = h.get('target')

        pnl_icon = '🟢' if pnl and pnl > 5 else '🟡' if pnl and pnl > 0 else '🔴'
        risk = ''
        if stop and si['close'] <= stop * 1.03:
            risk = ' ⚠️接近止损'
        if stop and si['close'] <= stop:
            risk = ' 🚨跌破止损!'

        mf_str = ''
        if si['main_net'] is not None:
            mf_yi = si['main_net'] / 1e8
            mf_str = f" | 主力{'+' if mf_yi >= 0 else ''}{mf_yi:.1f}亿"
        vol_str = f" | 量比{si['vol_ratio']:.2f}" if si['vol_ratio'] else ""

        print(f"  {pnl_icon} {name}({sc})  盈亏 {pnl:+.1f}%  现价 {si['close']:.2f}")
        print(f"     日涨跌 {si['change_pct']:+.2f}%  5日 {si['chg5']:+.1f}%{vol_str}{mf_str}")
        print(f"     {ma_status_line(si)}")
        print(f"     目标 {target}  止损 {stop}{risk}")
        print()

# ── 三、观察股 ──
print("三、观察股 (watch_active)")
print("-" * 50)

if not watch_active:
    print("  无活跃观察股")
else:
    for w in watch_active:
        sc, name = w['code'], w.get('name', '?')
        si = stock_indicators.get(sc)
        if not si:
            continue
        el, eh = w.get('entry_low'), w.get('entry_high')

        zone_str = ''
        if el and eh and si['close']:
            if el <= si['close'] <= eh:
                zone_str = ' 🎯买入区间'
            elif si['close'] < el * 0.995:
                zone_str = f' ⏳低于区间{abs((1-si["close"]/el)*100):.1f}%'
            elif si['close'] > eh * 1.05:
                zone_str = ' ⚠️超区间5%+'

        mf_str = ''
        if si['main_net'] is not None:
            mf_yi = si['main_net'] / 1e8
            mf_str = f"{'+' if mf_yi >= 0 else ''}{mf_yi:.1f}亿"
        vol_str = f"量比{si['vol_ratio']:.1f}" if si['vol_ratio'] else ""

        print(f"  {name}({sc})  {si['close']:.2f}  {si['change_pct']:+.2f}%")
        print(f"     5日{si['chg5']:+.1f}%  20日{si['chg20']:+.1f}%  {mf_str}  {vol_str}{zone_str}")
        print(f"     {ma_status_line(si)}")
        print()

# ── 四、今日关注 ──
print("四、今日关注")
print("-" * 50)

alerts = []

# Big movers
all_gainers = []
for p in holds + watch_active:
    si = stock_indicators.get(p['code'])
    if si and si['change_pct'] and si['change_pct'] >= 5:
        all_gainers.append((p, si))
all_gainers.sort(key=lambda x: x[1]['change_pct'], reverse=True)
if all_gainers:
    gs = [f"{p.get('name','?')}({si['change_pct']:+.1f}%)" for p, si in all_gainers[:5]]
    alerts.append(f"📈 周五大涨: {' '.join(gs)}")

# Volume breakout
high_vol = [(p, stock_indicators[p['code']]) for p in all_relevant
            if stock_indicators.get(p['code']) and stock_indicators[p['code']]['vol_ratio']
            and stock_indicators[p['code']]['vol_ratio'] > 2]
if high_vol:
    vs = [f"{p.get('name','?')}(量{si['vol_ratio']:.1f})" for p, si in high_vol[:3]]
    alerts.append(f"📊 放量: {' '.join(vs)}")

# Entry zone
in_zone = [w for w in watch_active
           if stock_indicators.get(w['code']) and w.get('entry_low') and w.get('entry_high')
           and w['entry_low'] <= stock_indicators[w['code']]['close'] <= w['entry_high']]
if in_zone:
    is_list = [f"{w.get('name','?')}({stock_indicators[w['code']]['close']:.0f})" for w in in_zone]
    alerts.append(f"🎯 买入区间内: {' '.join(is_list)}")

# Below zone
below_zone = [w for w in watch_active
              if stock_indicators.get(w['code']) and w.get('entry_low')
              and stock_indicators[w['code']]['close'] < w['entry_low'] * 0.98]
if below_zone:
    bs = [f"{w.get('name','?')}(低{abs((1-stock_indicators[w['code']]['close']/w['entry_low'])*100):.0f}%)" for w in below_zone]
    if bs:
        alerts.append(f"⏳低于区间(等回踩): {' '.join(bs)}")

# Near stop loss
near_stop = [h for h in holds
             if stock_indicators.get(h['code']) and h.get('stop_loss')
             and stock_indicators[h['code']]['close'] <= h['stop_loss'] * 1.05]
if near_stop:
    ns = [f"{h.get('name','?')}({stock_indicators[h['code']]['close']:.1f}/{h['stop_loss']})" for h in near_stop]
    alerts.append(f"🔴 近止损: {' '.join(ns)}")

# Near target
near_target = [h for h in holds
               if stock_indicators.get(h['code']) and h.get('target')
               and stock_indicators[h['code']]['close'] >= h['target'] * 0.95]
if near_target:
    nt = [f"{h.get('name','?')}(现{stock_indicators[h['code']]['close']:.0f}/目{h['target']})" for h in near_target]
    alerts.append(f"🎯 近目标: {' '.join(nt)}")

if not alerts:
    alerts.append("暂无重大异动")

for a in alerts:
    print(f"  {a}")

print()
print("=" * 60)
print(f"📅 数据截止: {ref_date}  生成: {datetime.datetime.now().strftime('%m-%d %H:%M')}")
print("💡 今日(6/15 周一) 9:30开盘")
