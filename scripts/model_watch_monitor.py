#!/usr/bin/env python3
"""
执行Agent — 盘中按规则自动买卖（原model_watch_monitor）
风控由agent_risk.py独立负责，选股由agent_picker.py负责
运行时: 盘中每10分钟
"""
import os, sys, json, urllib.request, http.cookiejar, subprocess
from datetime import datetime
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
HOLD_PATH = BASE / 'holdings.json'
LOG_PATH = BASE / 'model_watch_trades.json'
TRADE_URL = 'http://localhost:8080'
MAX_POSITIONS = 5
PER_POSITION_CAPITAL = 200000  # 每只固定20万
INITIAL_CAPITAL = 1000000
SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn'}

# 行业限制：同行业最多买N只
SECTOR_LIMITS = {
    'C39': 2,  # 计算机、通信—半导体等最多2只
    'I65': 2,  # 软件
}

def sina_code(code):
    if code in ('000001', '399001', '399006'):
        return {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}[code]
    pf = 'sh' if code.startswith(('6','68','920')) else 'sz'
    return f'{pf}{code}'

def fetch_realtime(codes):
    try:
        if not codes: return {}
        batch = ','.join(sina_code(c) for c in codes)
        req = urllib.request.Request(f'https://hq.sinajs.cn/list={batch}', headers=SINA_HEADERS)
        raw = urllib.request.urlopen(req, timeout=5).read().decode('gbk')
        result = {}
        for line in raw.strip().split(';\n'):
            if '=' not in line: continue
            k = line.split('=')[0].split('_')[-1]
            # 去掉市场前缀（sh/sz/bj）
            code = k[2:] if len(k) > 2 and k[:2] in ('sh','sz','bj') else k
            d = line.split('"')[1].split(',')
            if len(d) < 32: continue
            result[code] = {'name': d[0], 'open': float(d[1]) if d[1] else None,
                'close_y': float(d[2]) if d[2] else None,
                'price': float(d[3]) if d[3] else None,
                'high': float(d[4]) if d[4] else None,
                'low': float(d[5]) if d[5] else None,
                'amount': float(d[9]) if d[9] else 0,
                'change_pct': float(d[32]) if len(d)>32 and d[32] else None}
        return result
    except: return {}

def load_holdings():
    with open(HOLD_PATH) as f: return json.load(f)

def save_holdings(data):
    with open(HOLD_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def login():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return op

def api_get(op, path):
    try: return json.loads(op.open(urllib.request.Request(f'{TRADE_URL}{path}')).read())
    except: return {}

def api_trade(op, action, code, price, shares=None):
    d = {'action': action, 'code': code, 'price': price}
    if shares: d['shares'] = shares
    try:
        r = op.open(urllib.request.Request(f'{TRADE_URL}/api/trade',
            data=json.dumps(d).encode(), headers={'Content-Type':'application/json'})).read()
        return json.loads(r)
    except Exception as e:
        return {'ok': False, 'msg': str(e)}

_daily_scores = None
_DAILY_SCORE_DATE = None

def get_model_scores():
    global _daily_scores, _DAILY_SCORE_DATE
    today = datetime.now().strftime('%Y-%m-%d')
    # 先检查进程内缓存
    if _daily_scores is not None and _DAILY_SCORE_DATE == today:
        return _daily_scores
    # 再检查文件缓存（跨cron进程）
    cache_path = BASE / '_score_cache.json'
    try:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text())
            if cached.get('date') == today and len(cached.get('scores', {})) > 0:
                _daily_scores = cached['scores']
                _DAILY_SCORE_DATE = today
                return _daily_scores
    except: pass
    try:
        r = subprocess.run([sys.executable, str(BASE/'scripts/combined_score.py')],
            capture_output=True, text=True, cwd=str(BASE), timeout=120)
        scores = {}
        for line in r.stdout.split('\n'):
            parts = line.strip().split()
            if len(parts) >= 6 and parts[0].isdigit():
                try: scores[parts[1]] = float(parts[3])
                except: pass
        # 写入文件缓存
        cache_path.write_text(json.dumps({'date': today, 'scores': scores}))
        _daily_scores = scores
        _DAILY_SCORE_DATE = today
        return scores
    except Exception as e: return {}

def check_market_condition():
    """检查大盘是否适合买入：上证当日跌超2%暂停买入"""
    try:
        req = urllib.request.Request(f'https://hq.sinajs.cn/list=sh000001', headers=SINA_HEADERS)
        raw = urllib.request.urlopen(req, timeout=5).read().decode('gbk')
        d = raw.split('"')[1].split(',')
        if len(d) > 32:
            change = float(d[32])
            if change < -2:
                return False, f'大盘{change:.1f}%暂停买入'
        return True, ''
    except: return True, ''

def check_ma60_break(code):
    """连续N日收MA60下方统计"""
    import duckdb
    conn = duckdb.connect(str(BASE / 'stock.db'), read_only=True)
    rows = conn.execute(f"""
        SELECT t.close, AVG(t2.close) as ma60
        FROM stock_daily t
        JOIN stock_daily t2 ON t.stock_code = t2.stock_code
            AND t2.date BETWEEN t.date - 60 AND t.date - 1
        WHERE t.stock_code='{code}'
        GROUP BY t.date, t.close
        ORDER BY t.date DESC LIMIT 5
    """).fetchall()
    conn.close()
    if len(rows) < 3: return False, 0
    breaks = sum(1 for r in rows if r[0] < r[1])
    return breaks >= 3, breaks

def get_industry(code):
    """获取股票行业代码（前3位）"""
    import duckdb
    conn = duckdb.connect(str(BASE / 'stock.db'), read_only=True)
    r = conn.execute(f"SELECT industry FROM stock_info WHERE stock_code='{code}'").fetchone()
    conn.close()
    return r[0][:3] if r and r[0] else ''

def main():
    now = datetime.now()
    hm = now.hour * 100 + now.minute
    if hm < 930 or hm >= 1500 or (1130 <= hm < 1300):
        return

    data = load_holdings()
    watches = [p for p in data['positions'] if p.get('status') == 'watch_active']
    holds = [p for p in data['positions'] if p.get('status') == 'hold']
    watch_codes = [w['code'] for w in watches]
    hold_codes = [h['code'] for h in holds]
    all_codes = list(set(watch_codes + hold_codes))
    if not all_codes: return

    prices = fetch_realtime(all_codes)
    if not prices: return

    op = login()
    st = api_get(op, '/api/status')
    cash = st.get('cash', INITIAL_CAPITAL)
    sim_pos = st.get('positions', [])
    sim_map = {p['code']: p for p in sim_pos}
    scores = get_model_scores()
    market_ok, market_msg = check_market_condition()

    log = {'time': now.isoformat(), 'actions': []}

    # ─── 卖出检查 ───
    for h in holds:
        code = h['code']
        if code not in prices: continue
        p = prices[code]
        pr = p['price']
        if not pr: continue
        cost = h.get('buy_price', pr)
        pnl = (pr / cost - 1) * 100
        sp = sim_map.get(code)
        sh = sp['shares'] if sp else 0
        score = scores.get(code, h.get('model_score', 50))

        reasons = []
        do_sell = False
        sell_all = True
        sell_shares = sh

        # 0. 检查风控信号
        try:
            sig_path = BASE / 'risk_signals.json'
            if sig_path.exists():
                sigs = json.loads(sig_path.read_text()).get('signals', [])
                for sig in sigs:
                    if sig['code'] == code:
                        if sig['action'] == '清仓':
                            reasons.append(f"风控:{sig['reason']}")
                            do_sell = True
                        elif sig['action'] == '减半仓' and not h.get('half_sold', False):
                            reasons.append(f"风控:{sig['reason']}")
                            do_sell = True
                            sell_all = False
                            sell_shares = sh // 2
        except: pass

        # 1. 硬止损 -8%
        if pnl < -8:
            reasons.append(f'硬止损{pnl:.1f}%')
            do_sell = True

        # 2. 止盈半仓（达到目标）
        tg = h.get('target', 0)
        if tg and pr >= tg and not h.get('half_sold', False):
            reasons.append(f'达到目标{tg:.0f}')
            do_sell = True
            sell_all = False
            sell_shares = sh // 2

        # 3. 模型分连续走弱（需有历史记录才判断，首次不卖）
        prev_score = h.get('model_score')
        if prev_score is not None and score < 45 and prev_score < 45:
            reasons.append(f'模型分连续{score:.0f}/{prev_score:.0f}<45')
            do_sell = True

        # 4. 连续3日破MA60
        ma60_broken, n = check_ma60_break(code)
        if ma60_broken:
            reasons.append(f'连续{n}日破MA60')
            do_sell = True

        if not do_sell:
            # 更新持仓的模型分
            h['model_score'] = score
            continue

        if sell_all and sell_shares <= 0:
            continue
        if not sell_all and sell_shares <= 0:
            continue

        r = api_trade(op, 'sell', code, pr, sell_shares if not sell_all else None)
        if r.get('ok'):
            if not sell_all:
                h['half_sold'] = True
                h['note'] = h.get('note', '') + f' | 半仓止盈{now.strftime("%m/%d %H:%M")}'
            else:
                h['status'] = 'archived'
                h['archive_reason'] = f'自动平仓 {reasons[0]} pnl={pnl:.1f}%'
                h['sell_price'] = pr
                h['pnl_pct'] = round(pnl, 2)
            save_holdings(data)
        log['actions'].append({
            'type': 'sell_all' if sell_all else 'sell_half',
            'code': code, 'price': pr, 'pnl': round(pnl, 2),
            'reason': ' | '.join(reasons), 'ok': r.get('ok', False)
        })

    # ─── 买入检查 ───
    sim_codes = {p['code'] for p in sim_pos}
    active_codes = {p['code'] for p in holds}
    can_buy = MAX_POSITIONS - len(sim_pos)

    if can_buy > 0 and market_ok:
        # 统计已有持仓的行业分布
        sector_count = {}
        for h in holds:
            ind = get_industry(h['code'])
            if ind: sector_count[ind] = sector_count.get(ind, 0) + 1

        for w in watches:
            code = w['code']
            if code in sim_codes or code in active_codes: continue
            if code not in prices: continue
            p = prices[code]
            pr = p['price']
            if not pr: continue
            chg = p.get('change_pct', 0)
            score = scores.get(code, w.get('model_score', 50))
            reasons = []

            # 条件0：检查介入区间（如设定了）
            entry_low = w.get('entry_low')
            entry_high = w.get('entry_high')
            if entry_low and entry_high:
                if pr < entry_low or pr > entry_high:
                    continue  # 不在介入区间，不买
            reasons.append(f'介入区间{entry_low}~{entry_high}' if entry_low else '')

            # 条件1：非涨跌停
            if chg and abs(chg) >= 9.5:
                continue

            # 条件2：有一定成交量
            if p['amount'] < 5e6:
                continue

            # 条件3：距MA60不过分远（不设站MA60硬条件）
            import duckdb
            conn = duckdb.connect(str(BASE / 'stock.db'), read_only=True)
            ma60_row = conn.execute(f"""
                SELECT AVG(close) FROM stock_daily
                WHERE stock_code='{code}' AND date >= (SELECT MAX(date)-60 FROM stock_daily WHERE stock_code='{code}')
            """).fetchone()
            ma60 = ma60_row[0] if ma60_row else 0
            conn.close()
            if ma60 and pr < ma60 * 0.85:
                continue  # 低于MA60超过15%说明深度破位，不买
            reasons.append(f'距MA60 {pr/ma60-1:+.1f}%' if ma60 else '')

            # 条件4：模型分≥50（候选池门槛）
            if score < 50:
                continue
            reasons.append(f'模型{score:.0f}分')

            # 条件5：行业限制
            ind = get_industry(code)
            if ind and ind in SECTOR_LIMITS:
                current = sector_count.get(ind, 0) + sum(1 for ww in watches
                    if ww.get('status') == 'hold' and get_industry(ww['code']) == ind)
                if current >= SECTOR_LIMITS[ind]:
                    continue

            # 全通过 → 买入
            shares = max(100, int(PER_POSITION_CAPITAL / pr / 100) * 100)
            r = api_trade(op, 'buy', code, pr, shares)
            if r.get('ok'):
                w['status'] = 'hold'
                w['buy_date'] = now.strftime('%Y-%m-%d')
                w['buy_price'] = pr
                w['model_score'] = score
                w['shares'] = shares
                w['note'] = w.get('note', '') + f' | 建仓{shares}股@{pr}'
                save_holdings(data)
                can_buy -= 1
            log['actions'].append({
                'type': 'buy', 'code': code, 'price': pr,
                'shares': shares, 'score': score,
                'ok': r.get('ok', False), 'msg': r.get('msg', '')
            })
            if can_buy <= 0: break

    # 更新持仓的模型分（没有触发买卖也记录最新分）
    for h in holds:
        code = h['code']
        if code in scores:
            h['model_score'] = scores[code]
    save_holdings(data)

    if log['actions']:
        history = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
        history.append(log)
        LOG_PATH.write_text(json.dumps(history[-200:], ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
