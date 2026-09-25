#!/usr/bin/env python3
"""
短线盘中监控+执行器 v1 — 独立交易系统
每5-10分钟运行一次（no_agent=true）
- 实时监控 short_watch 候选
- 符合买入条件 → 从 short_account 直接买入
- 监控 short_positions 的卖出条件

完全不碰 holdings.json / account.json / simulate.py
仅供读 stock.db（read_only）获取技术数据
"""
import os, sys, json, urllib.request, duckdb
from datetime import datetime, date
from pathlib import Path

# 清理代理
for k in ['http_proxy','https_proxy','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
    os.environ.pop(k, None)

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'
SHORT_HOLD_PATH = BASE / 'short_holdings.json'
SHORT_ACCT_PATH = BASE / 'short_account.json'
SHORT_LOG_PATH = BASE / 'short_trade_log.json'
SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn'}

MAX_POSITIONS = 5
POSITION_CAPITAL = 80000  # 每只8万（50万/5只≈10万，留余量）
ONE_MONITOR = 1
INITIAL_CAPITAL = 500000

# ── QQ通知（写入 pending_alerts.json，和中长线共享） ──
ALERT_PATH = BASE / 'pending_alerts.json'

def notify_qq(action, code, name, price, shares, reason='', pnl=None):
    try:
        entry = {
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'time': datetime.now().strftime('%m-%d %H:%M'),
            'action': action, 'code': code, 'name': name,
            'price': round(price, 2), 'shares': shares,
            'reason': reason,
        }
        if pnl is not None:
            entry['pnl'] = round(pnl, 2)
        alerts = []
        if ALERT_PATH.exists():
            try: alerts = json.loads(ALERT_PATH.read_text())
            except: pass
        alerts.append(entry)
        if len(alerts) > 10: alerts = alerts[-10:]
        ALERT_PATH.write_text(json.dumps(alerts, ensure_ascii=False, indent=2))
    except: pass

def sigmoid_code(code):
    if code in ('000001', '399001', '399006'):
        m = {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}
        return m[code]
    pf = 'sh' if code.startswith(('6','68','920')) else 'sz'
    return f'{pf}{code}'

def fetch_realtime(codes):
    """批量获取实时行情"""
    if not codes:
        return {}
    try:
        batch = ','.join(sigmoid_code(c) for c in codes)
        req = urllib.request.Request(f'https://hq.sinajs.cn/list={batch}', headers=SINA_HEADERS)
        raw = urllib.request.urlopen(req, timeout=5).read().decode('gbk')
        result = {}
        for line in raw.strip().split(';\n'):
            if '=' not in line:
                continue
            k = line.split('=')[0].split('_')[-1]
            code = k[2:] if len(k) > 2 and k[:2] in ('sh','sz','bj') else k
            d = line.split('"')[1].split(',')
            if len(d) < 32:
                continue
            result[code] = {
                'name': d[0],
                'open': float(d[1]) if d[1] else None,
                'close_y': float(d[2]) if d[2] else None,
                'price': float(d[3]) if d[3] else None,
                'high': float(d[4]) if d[4] else None,
                'low': float(d[5]) if d[5] else None,
                'volume': float(d[8]) if d[8] else 0,
                'amount': float(d[9]) if d[9] else 0,
                'change_pct': float(d[32]) if len(d) > 32 and d[32] else None,
            }
        return result
    except Exception as e:
        return {}

def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(open(path).read())
    except:
        return default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_ma_data(code, conn):
    """获取历史收盘价计算均线"""
    rows = conn.execute(f"""
        SELECT close FROM stock_daily WHERE stock_code='{code}'
        ORDER BY date DESC LIMIT 120
    """).fetchall()
    if len(rows) < 20:
        return None
    closes = [float(r[0]) for r in rows][::-1]
    price = closes[-1]
    ma5 = sum(closes[-5:])/5
    ma10 = sum(closes[-10:])/10
    ma20 = sum(closes[-20:])/20
    ma60 = sum(closes[-60:])/60 if len(closes) >= 60 else ma20
    ma120 = sum(closes)/len(closes)
    dev120 = (price/ma120 - 1)*100 if ma120 > 0 else 0
    return {
        'price': price, 'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
        'ma60': ma60, 'ma120': ma120, 'dev120': dev120,
        'bull_ma': ma5 > ma10 > ma20 > ma60  # 多头排列
    }

def check_market_condition(conn):
    """大盘氛围检查：大盘跌超1.5%时不建新仓"""
    rows = conn.execute("""
        SELECT change_pct FROM index_daily
        WHERE index_code='000001' ORDER BY date DESC LIMIT 1
    """).fetchall()
    if rows and rows[0][0] is not None:
        chg = rows[0][0]
        if chg < -1.5:
            return False, f'大盘跌{chg:.1f}% 暂停建仓'
    return True, '正常'

def main():
    now = datetime.now()
    hm = now.hour * 100 + now.minute
    # 非交易时段静默退出
    if hm < 930 or hm >= 1500 or (1130 <= hm < 1300):
        return

    print("="*50)
    print(f"📡 短线监控执行器 — {now.strftime('%Y-%m-%d %H:%M')}")
    print("="*50)

    # 读独立持仓/账户
    sh_data = load_json(SHORT_HOLD_PATH, {"short_positions": [], "short_watch": [], "initial_capital": 500000})
    acct = load_json(SHORT_ACCT_PATH, {"cash": INITIAL_CAPITAL, "positions": []})
    conn = duckdb.connect(str(DB_PATH), read_only=True)

    positions = sh_data.get('short_positions', [])
    watches = sh_data.get('short_watch', [])
    cash = acct.get('cash', INITIAL_CAPITAL)
    pos_map = {p['code']: p for p in positions}

    # 大盘状态
    market_ok, market_msg = check_market_condition(conn)
    print(f"  大盘: {market_msg}")

    if not watches and not positions:
        print("  无观察股和持仓")
        conn.close()
        return

    log_entries = []

    # ── 卖出检查（先卖后买）──
    pos_prices = {}
    if positions:
        codes = [p['code'] for p in positions]
        prices = fetch_realtime(codes)
        pos_prices = prices  # 保存持仓行情，防止被买入模块覆盖
        print(f"\n🔴 检查持仓 {len(positions)} 只...")

        for p in positions[:]:
            code = p['code']
            if code not in prices:
                continue
            rp = prices[code]
            pr = rp['price']
            if not pr:
                continue
            chg = rp.get('change_pct', 0)
            cost = p.get('buy_price', pr)
            pnl = (pr / cost - 1) * 100
            ma = get_ma_data(code, conn)

            reasons = []
            do_sell = False
            sell_all = True

            # 条件1: 硬止损 -7%（短线比长线严格）
            if pnl < -7:
                reasons.append(f'硬止损{pnl:.1f}%')
                do_sell = True

            # 条件2: 技术破位
            if ma and not ma['bull_ma']:
                if ma['dev120'] < -15:
                    reasons.append(f'深度破位(120={ma["dev120"]:.0f}%)')
                    do_sell = True

            # 条件3: 达目标止盈
            tg = p.get('target', 0)
            if tg and pr >= tg:
                if p.get('half_sold'):
                    reasons.append(f'达目标{tg}清仓')
                    do_sell = True
                else:
                    p['half_sold'] = True
                    p['note'] = p.get('note', '') + f' | 半仓止盈@{pr}'
                    reasons.append(f'达目标{tg}减半')
                    do_sell = True
                    sell_all = False

            # 条件4: 信号转负（当日跌幅>5%或连续弱势）
            if chg and chg < -5:
                reasons.append(f'日内暴跌{chg:.1f}%')
                do_sell = True

            # 条件5: 持有超10个交易日止盈保护
            buy_date_str = p.get('buy_date', '')
            if buy_date_str:
                try:
                    hold_days = (date.today() - datetime.strptime(buy_date_str, '%Y-%m-%d').date()).days
                    if hold_days >= 10 and pnl > 0:
                        reasons.append(f'持有{hold_days}天止盈')
                        do_sell = True
                except:
                    pass

            if not do_sell:
                continue

            # 执行卖出
            shares = p.get('shares', 0)
            sell_shares = shares if sell_all else shares // 2
            if sell_shares <= 0:
                continue

            # 扣除仓位
            sell_value = sell_shares * pr
            cost_value = sell_shares * cost

            if sell_all:
                positions.remove(p)
                p['status'] = 'archived'
                p['sell_price'] = pr
                p['pnl_pct'] = round(pnl, 2)
                msg = f"清仓 {sell_shares}股@{pr} pnl={pnl:.1f}%"
            else:
                p['shares'] = shares - sell_shares
                msg = f"减半 {sell_shares}股@{pr}"
            cash += sell_value

            log_entries.append({
                'time': now.isoformat(), 'type': 'sell_all' if sell_all else 'sell_half',
                'code': code, 'price': pr, 'shares': sell_shares,
                'pnl': round(pnl, 2), 'reason': ' | '.join(reasons)
            })
            print(f"  💀 {code} {p['name']} {msg} {' | '.join(reasons)}")
            notify_qq('卖出' if sell_all else '减仓', code, p['name'], pr, sell_shares,
                      ' | '.join(reasons), pnl=pnl)

    # ── 买入检查 ──
    if watches and market_ok:
        watch_codes = [w['code'] for w in watches]
        prices = fetch_realtime(watch_codes)
        slots = MAX_POSITIONS - len(positions)

        if slots > 0 and cash >= 10000:
            print(f"\n🟢 检查买入 (空位{slots}, 现金{cash:,.0f})...")

            # 统计已有行业
            sector_count = {}
            for p in positions:
                try:
                    ind = conn.execute(f"SELECT industry FROM stock_info WHERE stock_code='{p['code']}'").fetchone()
                    if ind and ind[0] and len(ind[0]) >= 3:
                        sector_count[ind[0][:3]] = sector_count.get(ind[0][:3], 0) + 1
                except:
                    pass

            watches.sort(key=lambda w: w.get('signal_score', 0), reverse=True)

            for w in watches[:]:
                code = w['code']
                if code in pos_map:
                    continue
                if code not in prices:
                    continue
                rp = prices[code]
                pr = rp['price']
                if not pr:
                    continue
                chg = rp.get('change_pct', 0)

                # 条件1: 价格在介入区间
                entry_low = w.get('entry_low')
                entry_high = w.get('entry_high')
                if entry_low and entry_high:
                    if pr < entry_low or pr > entry_high:
                        continue

                # 条件2: 非涨跌停
                if chg and abs(chg) >= 9.5:
                    continue

                # 条件3: 有一定成交量（盘中500万以上）
                if rp.get('amount', 0) < 5e6:
                    continue

                # 条件4: 距MA60不过分远
                ma = get_ma_data(code, conn)
                if ma and ma['dev120'] < -20:
                    continue  # 深度破位不买

                # 条件5: 行业限制
                ind_row = conn.execute(f"SELECT industry FROM stock_info WHERE stock_code='{code}'").fetchone()
                if ind_row and ind_row[0] and len(ind_row[0]) >= 3:
                    ind3 = ind_row[0][:3]
                    if sector_count.get(ind3, 0) >= 2:
                        continue

                # 全通过 → 买入
                shares = max(100, int(POSITION_CAPITAL / pr / 100) * 100)
                buy_value = shares * pr
                if buy_value > cash:
                    continue

                entry = {
                    'code': code,
                    'name': w['name'],
                    'shares': shares,
                    'buy_price': pr,
                    'buy_date': now.strftime('%Y-%m-%d'),
                    'stop_loss': w.get('stop_loss', round(pr * 0.92, 2)),
                    'target': w.get('target', round(pr * 1.10, 2)),
                    'style': w.get('style', ''),
                    'note': f'自动建仓 {shares}股@{pr}'
                }
                positions.append(entry)
                cash -= buy_value
                pos_map[code] = entry
                slots -= 1

                # 从观察池移除
                watches = [x for x in watches if x['code'] != code]

                log_entries.append({
                    'time': now.isoformat(), 'type': 'buy',
                    'code': code, 'price': pr, 'shares': shares,
                    'score': w.get('signal_score', 0), 'style': w.get('style', '')
                })
                print(f"  ✅ {code} {w['name']} {w.get('style','')} {w.get('signal_score',0):.0f}分 "
                      f"{shares}股@{pr}")
                notify_qq('买入', code, w['name'], pr, shares, f'短线介入区间{w.get("entry_low","?")}~{w.get("entry_high","?")}')

                if slots <= 0:
                    break

    # ── 保存 ──
    sh_data['short_positions'] = positions
    sh_data['short_watch'] = watches
    save_json(SHORT_HOLD_PATH, sh_data)

    acct['cash'] = cash
    acct['positions'] = [{'code': p['code'], 'name': p['name'], 'shares': p['shares'],
                          'avg_cost': p['buy_price'], 'buy_date': p['buy_date']}
                         for p in positions]
    acct['updated_at'] = now.isoformat()
    save_json(SHORT_ACCT_PATH, acct)

    # 日志
    if log_entries:
        history = load_json(SHORT_LOG_PATH, [])
        history.extend(log_entries)
        save_json(SHORT_LOG_PATH, history[-500:])

    # 汇总
    hit_count = sum(1 for p in positions
                    if pos_prices.get(p['code'], {}).get('price', p['buy_price']) > p['buy_price'])
    hit_rate = round(hit_count / max(len(positions), 1) * 100, 1)
    print(f"\n{'='*50}")
    print(f"📊 短线持仓: {len(positions)} 只  观察: {len(watches)} 只  现金: {cash:,.0f}  命中率: {hit_rate}%")
    for p in positions:
        code = p['code']
        rp = pos_prices.get(code, {})
        pr = rp.get('price', p['buy_price'])
        pnl = (pr/p['buy_price'] - 1)*100
        print(f"  {code} {p['name']} {p['shares']}股  盈亏{pnl:+.1f}%")
    conn.close()

if __name__ == '__main__':
    main()
