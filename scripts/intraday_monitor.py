#!/usr/bin/env python3
""""
盘中智能监控 v3 — 持仓三态决策引擎
每15分钟运行一次 (no_agent=true)

持仓决策三态：
  卖出 — 放量破止损 | 达目标 | 持有到期无趋势 | 量价背离
  补仓 — 缩量回调到成本下 | 回踩介入区+缩量 | 急跌无利空
  持有 — 其他一切情况

新增：
- 持仓技术面（MA5方向、量比、成本距离）
- 补仓质量评分（回调深度+缩量程度+大盘环境）
- 卖出紧急度（真破位 vs 假摔）
- DB查询MA5和近期量能（仅开盘后查一次）
- 大涨大跌异动检测（所有股票通用，>7%涨或<-5%跌报警）
"""

import os, sys, json, urllib.request
from datetime import datetime, timedelta

for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

# ── 收盘保护：非交易时段直接退出 ──
now = datetime.now()
if now.hour < 9 or now.hour > 14 or (now.hour == 11 and now.minute >= 30) or (now.hour == 12):
    sys.exit(0)

HOLD_PATH = os.path.expanduser('~/.hermes/stockdb/holdings.json')
STATE_PATH = os.path.expanduser('~/.hermes/stockdb/alert_state.json')
HIST_PATH = os.path.expanduser('~/.hermes/cache/price_history.json')
TODAY = datetime.now().strftime('%Y-%m-%d')

INDEX_SYMBOLS = {'sh000001': '上证指数', 'sz399001': '深证成指', 'sz399006': '创业板指'}

def sina_code(code):
    if code in ('000001', '399001', '399006'):
        return {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}[code]
    return f'sh{code}' if code.startswith(('6','68')) else f'sz{code}'

def load_json(path, default=None):
    if default is None: default = {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

def fetch_quote(symbol):
    try:
        url = f"https://hq.sinajs.cn/list={symbol}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=5).read()
        text = raw.decode('gbk')
        if '=""' in text: return None
        parts = text.split('"')[1].split(',')
        if len(parts) < 10: return None
        cur, yest = float(parts[3]), float(parts[2])
        return {
            'name': parts[0], 'price': cur,
            'change': round((cur-yest)/yest*100, 2),
            'high': float(parts[4]), 'low': float(parts[5]),
            'open': float(parts[1]), 'prev_close': yest,
            'amount': float(parts[9])/1e8 if parts[9] else 0,
        }
    except:
        return None

def load_tech_data(codes):
    """从DB加载MA5和近期量能（仅对有持仓时调用）"""
    try:
        import duckdb
        db = os.path.expanduser('~/.hermes/stockdb/tushare.db')
        conn = duckdb.connect(db)
        today = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
        today_str = today.isoformat() if today else TODAY

        # 获取最近5天的量能和MA5
        code_list = "','".join(codes)
        rows = conn.execute(f"""
            WITH recent AS (
                SELECT stock_code, close, volume, date,
                       ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY date DESC) as rn
                FROM stock_daily
                WHERE stock_code IN ('{code_list}') AND date <= '{today_str}'
            ),
            ma5 AS (
                SELECT stock_code, AVG(close) as price_ma5
                FROM recent WHERE rn BETWEEN 2 AND 6  -- 近5日不含今天
                GROUP BY stock_code
            ),
            vol_avg AS (
                SELECT stock_code, AVG(volume) as vol_ma5
                FROM recent WHERE rn BETWEEN 2 AND 6
                GROUP BY stock_code
            ),
            vol_trend AS (
                SELECT stock_code,
                       MAX(CASE WHEN rn=2 THEN volume END) as vol_today,
                       MAX(CASE WHEN rn=3 THEN volume END) as vol_yest,
                       MAX(CASE WHEN rn=4 THEN volume END) as vol_2ago
                FROM recent GROUP BY stock_code
            )
            SELECT r.stock_code, r.close as prev_close, m.price_ma5, v.vol_ma5,
                   vt.vol_today, vt.vol_yest, vt.vol_2ago
            FROM (SELECT stock_code, close FROM recent WHERE rn=2) r
            LEFT JOIN ma5 m ON r.stock_code=m.stock_code
            LEFT JOIN vol_avg v ON r.stock_code=v.stock_code
            LEFT JOIN vol_trend vt ON r.stock_code=vt.stock_code
        """).fetchall()

        tech = {}
        for row in rows:
            code, prev_close, ma5, vma5, vt, vy, v2 = row
            vol_ratio = (vt / vma5) if vt and vma5 and vma5 > 0 else 1.0
            vol_trend_up = (vt and vy and vt > vy * 1.1)  # 放量
            vol_trend_down = (vt and vy and vt < vy * 0.9)  # 缩量
            tech[code] = {
                'prev_close': prev_close,
                'ma5': ma5,
                'vol_ratio': round(vol_ratio, 2),
                'vol_trend_up': vol_trend_up,
                'vol_trend_down': vol_trend_down,
            }
        conn.close()
        return tech
    except:
        return {}

def time_context():
    h = datetime.now().hour; m = datetime.now().minute
    if h == 9 and m < 45: return 'morning_volatile'
    if h < 11: return 'morning_stable'
    if h == 11 or (h == 13 and m < 30): return 'lunch_edge'
    if h < 14: return 'afternoon'
    return 'closing'

def market_ok(index_quotes):
    for q in index_quotes.values():
        if q and q['change'] < -2.5:
            return False, f"大盘暴跌{q['change']:.1f}%"
    return True, ""

# ═══════════════════════════════════════
# 持仓三态决策
# ═══════════════════════════════════════

def decide_hold(code, info, quote, tech, alerts, prev_price, index_quotes):
    """
    返回 (decision, text, important)
    decision: 'SELL' | 'ADD' | 'HOLD'
    """
    price = quote['price']
    name = info['name']
    sl = info.get('stop_loss')
    tg = info.get('target')
    bp = info.get('buy_price')
    el = info.get('entry_low')
    buy_date = info.get('buy_date')
    t = tech or {}

    if not bp: return 'HOLD', None, False

    pnl_pct = (price - bp) / bp * 100
    ma5 = t.get('ma5')
    vol_ratio = t.get('vol_ratio', 1.0)
    vol_down = t.get('vol_trend_down', False)

    # ── 卖出判断 ──
    sell_text, sell_sig = check_sell_signal(code, name, price, sl, tg, bp, buy_date, vol_ratio, pnl_pct, alerts)
    if sell_text:
        return 'SELL', sell_text, True

    # ── 补仓判断 ──
    add_text, add_sig = check_add_signal(code, name, price, sl, bp, el, ma5, vol_down, pnl_pct, index_quotes, alerts)
    if add_text:
        return 'ADD', add_text, True

    # ── 持有状态汇报（非紧急） ──
    hold_text = hold_status(name, code, price, bp, sl, ma5, pnl_pct, buy_date)
    if hold_text and alerts.get(f"{code}_status") != TODAY:
        return 'HOLD', hold_text, False

    return 'HOLD', None, False


def check_sell_signal(code, name, price, sl, tg, bp, buy_date, vol_ratio, pnl_pct, alerts):
    """卖出信号判断 — 返回 (text, sig_id) 或 (None, None)"""

    # 1. 放量破止损
    if sl and price <= sl:
        sig = 'stop_loss'
        if alerts.get(f"{code}_{sig}") == TODAY: return None, None
        vol_tag = "放量真跌破" if vol_ratio > 1.2 else "缩量假摔(需确认)"
        if vol_ratio > 1.2:
            return f"🚨 {name}({code}) 放量跌破止损{sl} 现价{price:.2f} 浮亏{pnl_pct:+.1f}% — 建议立即卖出", sig
        else:
            return f"⚠️ {name}({code}) 缩量跌破止损{sl} 现价{price:.2f} — 量小可能是洗盘，关注下个15分钟是否拉回", sig

    # 2. 达目标
    if tg and price >= tg:
        sig = 'target_full'
        if alerts.get(f"{code}_{sig}") == TODAY: return None, None
        return f"🎯 {name}({code}) 达目标{tg} 现价{price:.2f} 盈利{pnl_pct:+.1f}% — 建议全出", sig

    # 3. 持有到期+无趋势（10天±5%震荡）
    if buy_date:
        try:
            held = (datetime.now() - datetime.strptime(str(buy_date), '%Y-%m-%d')).days
            if held >= 8 and abs(pnl_pct) < 5:
                sig = 'hold_stale'
                if alerts.get(f"{code}_{sig}") == TODAY: return None, None
                return f"⏰ {name}({code}) 持有{held}天仅变{pnl_pct:+.1f}% — 时间成本高，考虑换股", sig
        except: pass

    # 4. 接近止损+趋势恶化（价格下移）
    if sl and sl < price <= sl * 1.03:
        sig = 'near_stop'
        if alerts.get(f"{code}_{sig}") == TODAY: return None, None
        return f"⚡ {name}({code}) 距止损{sl}仅{(price-sl)/sl*100:.1f}% 现价{price:.2f} — 跌破即执行", sig

    return None, None


def check_add_signal(code, name, price, sl, bp, el, ma5, vol_down, pnl_pct, index_quotes, alerts):
    """补仓信号判断 — 返回 (text, sig_id) 或 (None, None)"""

    if not bp: return None, None

    # 大盘暴跌不补
    ok, reason = market_ok(index_quotes)
    if not ok: return None, None

    score = 0
    reasons = []

    # A. 缩量回调到成本下方（主力洗盘经典形态）
    below_cost = price < bp
    if below_cost and vol_down and sl and price > sl:
        depth = (bp - price) / bp * 100
        if 2 <= depth <= 8:
            score += 40
            reasons.append(f'缩量回踩成本-{depth:.1f}%')
        elif depth < 2:
            score += 20
            reasons.append('微调近成本')

    # B. 回踩介入区+缩量
    if el and price >= el * 0.97 and price <= el * 1.05:
        if vol_down:
            score += 30
            reasons.append('回踩介入区缩量')
        else:
            score += 15
            reasons.append('在介入区附近')

    # C. MA5支撑
    if ma5 and price > ma5:
        score += 15
        reasons.append('MA5上方')
    elif ma5 and price > ma5 * 0.98:
        score += 10
        reasons.append('MA5附近')

    # D. 急跌无利空（跌>5%但缩量=恐慌盘）
    if pnl_pct < -5 and vol_down and sl and price > sl:
        score += 15
        reasons.append('急跌缩量(恐慌盘)')

    if score >= 50 and alerts.get(f"{code}_add_{score//20}") != TODAY:
        label = '💰 强烈补仓' if score >= 70 else '💡 可补仓' if score >= 50 else '👀 观察'
        return f"{label} {name}({code}) 现价{price:.2f} 浮亏{pnl_pct:+.1f}% ({'; '.join(reasons)}) 得分{score}", f"add_{score//20}"

    return None, None


def hold_status(name, code, price, bp, sl, ma5, pnl_pct, buy_date):
    """持有状态简报（非紧急）"""
    parts = [f"📌 {name}({code}) 现价{price:.2f}"]
    if pnl_pct >= 0:
        parts.append(f"浮盈{pnl_pct:+.1f}%")
    else:
        parts.append(f"浮亏{pnl_pct:.1f}%")

    if sl:
        dist = (price - sl) / sl * 100
        if dist < 5: parts.append(f"距止损{dist:.1f}%")
    if ma5:
        ma5_dist = (price - ma5) / ma5 * 100
        tag = "站上MA5" if ma5_dist > 0 else "跌破MA5"
        parts.append(f"{tag}({ma5_dist:+.1f}%)")

    if buy_date:
        try:
            held = (datetime.now() - datetime.strptime(str(buy_date), '%Y-%m-%d')).days
            parts.append(f"持有{held}天")
        except: pass

    return ' | '.join(parts)


# ═══════════════════════════════════════
# 观察股买入判断
# ═══════════════════════════════════════

def check_entry(code, info, quote, alerts, index_quotes):
    price = quote['price']; name = info['name']
    el, eh = info.get('entry_low'), info.get('entry_high')
    if not el or not eh: return None
    if not (el <= price <= eh): return None

    ok, reason = market_ok(index_quotes)
    if not ok:
        sig = 'entry_blocked'
        if alerts.get(f"{code}_{sig}") == TODAY: return None
        return f"⛔ {name}({code}) 进入区间{el}-{eh} 但{reason}"

    # 质量评分
    score = 0
    h, l = quote['high'], quote['low']
    intra = (price - l) / (h - l) if h > l else 0.5
    if intra < 0.4: score += 30
    elif intra < 0.6: score += 20
    elif intra < 0.8: score += 10

    amt = quote.get('amount', 0)
    if amt > 5: score += 30
    elif amt > 2: score += 20
    elif amt > 0.5: score += 10

    chg = quote['change']
    if -2 <= chg <= 2: score += 20
    elif -3 <= chg < 0: score += 25

    tc = time_context()
    if tc == 'closing': score += 20
    elif tc == 'afternoon': score += 15

    sig = f"entry_{score//20}"
    if alerts.get(f"{code}_{sig}") == TODAY: return None

    if score >= 70:
        return f"🌟 强烈买入 {name}({code}) 区间{el}-{eh} 现价{price:.2f} 质量{score}分"
    elif score >= 50:
        return f"💡 可以买入 {name}({code}) 现价{price:.2f} 质量{score}分"
    return None


# ═══════════════════════════════════════
# 大涨大跌异动检测（所有股票通用）
# ═══════════════════════════════════════

def check_extreme_move(code, info, quote, alerts):
    """检测大涨(>7%)或大跌(<-5%)异动，返回 (text, sig_id) 或 (None, None)"""
    chg = quote['change']
    name = info.get('name', code)
    price = quote['price']

    if chg >= 7:
        sig = 'surge'
        if alerts.get(f"{code}_{sig}") == TODAY: return None, None
        return f"🔥 {name}({code}) 大涨+{chg:.1f}% 现价{price:.2f} — 注意追高风险", sig

    if chg <= -5:
        sig = 'plunge'
        if alerts.get(f"{code}_{sig}") == TODAY: return None, None
        return f"⚠️ {name}({code}) 大跌{chg:.1f}% 现价{price:.2f} — 关注是否破位", sig

    return None, None


# ═══════════════════════════════════════
# 主流程
# ═══════════════════════════════════════

def main():
    now = datetime.now()
    now_str = now.strftime('%H:%M')
    hour, minute = now.hour, now.minute

    if (hour == 11 and minute >= 31) or hour == 12: return
    if now.weekday() >= 5: return
    if hour < 9 or hour >= 15: return

    data = load_json(HOLD_PATH)
    positions = data.get('positions', [])
    if not positions: return

    alerts = load_json(STATE_PATH)
    if alerts.get('date') != TODAY:
        alerts = {'date': TODAY, 'alerts': {}}
    alert_map = alerts.get('alerts', {})

    price_hist = load_json(HIST_PATH, {'date': TODAY, 'prices': {}})
    if price_hist.get('date') != TODAY:
        price_hist = {'date': TODAY, 'prices': {}}
    prev_prices = price_hist.get('prices', {})
    new_prices = {}

    # ── 加载技术面 ──
    hold_codes = [p['code'] for p in positions if p.get('status') == 'hold']
    tech_data = load_tech_data(hold_codes) if hold_codes else {}

    # ── 大盘 ──
    index_quotes = {}
    for sym, name in INDEX_SYMBOLS.items():
        q = fetch_quote(sym)
        if q: index_quotes[sym] = q

    # ── 扫描 ──
    sell_signals = []
    add_signals = []
    entry_signals = []
    surge_signals = []
    hold_summary = []
    new_alerts = {}
    has_important = False

    for code, info in {p['code']: p for p in positions}.items():
        q = fetch_quote(sina_code(code))
        if not q: continue

        new_prices[code] = q['price']
        status = info.get('status', 'watch')
        if status == 'sold': continue  # 已平仓，跳过
        prev = prev_prices.get(code)
        tech = tech_data.get(code, {})

        if status == 'hold':
            decision, text, imp = decide_hold(code, info, q, tech, alert_map, prev, index_quotes)
            if decision == 'SELL' and text:
                sell_signals.append(text)
                has_important = True
            elif decision == 'ADD' and text:
                add_signals.append(text)
                has_important = True
            elif text:
                hold_summary.append(text)
            if text and decision:
                new_alerts[f"{code}_{decision}"] = TODAY

        elif status == 'watch':
            text = check_entry(code, info, q, alert_map, index_quotes)
            if text:
                entry_signals.append(text)
                has_important = True
                new_alerts[f"{code}_entry"] = TODAY

        # ── 对所有股票检查大涨大跌异动 ──
        extreme_text, extreme_sig = check_extreme_move(code, info, q, alert_map)
        if extreme_text:
            surge_signals.append(extreme_text)
            has_important = True
            new_alerts[f"{code}_{extreme_sig}"] = TODAY

    # ── 保存 ──
    price_hist['prices'] = new_prices
    save_json(HIST_PATH, price_hist)

    if new_alerts:
        alert_map.update(new_alerts)
        alerts['alerts'] = alert_map
        save_json(STATE_PATH, alerts)

    # ── 输出 ──
    all_parts = []

    if sell_signals:
        all_parts.append("🔴 卖出信号")
        all_parts.append("─" * 40)
        all_parts.extend(sell_signals)

    if add_signals:
        if all_parts: all_parts.append("")
        all_parts.append("🟢 补仓信号")
        all_parts.append("─" * 40)
        all_parts.extend(add_signals)

    if entry_signals:
        if all_parts: all_parts.append("")
        all_parts.append("💡 买入信号（观察股）")
        all_parts.append("─" * 40)
        all_parts.extend(entry_signals)

    if surge_signals:
        if all_parts: all_parts.append("")
        all_parts.append("⚡ 异动预警")
        all_parts.append("─" * 40)
        all_parts.extend(surge_signals)

    if not all_parts:
        return  # 静默

    tc = time_context()
    tc_name = {'morning_volatile':'早盘','morning_stable':'上午','lunch_edge':'午盘','afternoon':'下午','closing':'尾盘'}.get(tc, '')
    header = f"🔔 {now_str} 盘中决策 ({tc_name})"
    if has_important:
        header = f"🔴 {now_str} 盘中决策 ⚠️"

    print(header)
    print("\n".join(all_parts))

    if hold_summary and not has_important:
        print(f"\n📌 持仓概况")
        for h in hold_summary:
            print(f"  {h}")

if __name__ == '__main__':
    main()
