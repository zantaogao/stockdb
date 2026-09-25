#!/usr/bin/env python3
"""风控执行器 v2 — 最大化夏普操作指南
盘中所2分钟轮询评分信号并执行买卖。

规则来源：最大化夏普操作指南
"""
import json, urllib.request, http.cookiejar, sys, os, time, gzip, pickle
import numpy as np
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime, date, timedelta
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'
TRADE_URL = 'http://localhost:8080'
INITIAL_CAPITAL = 1_000_000
ALERT_PATH = BASE / 'pending_alerts.json'

# 统一价格接口（TDX ↔ Sina 并发，DB兜底）
sys.path.insert(0, str(BASE))
from core.prices import fetch_price_live as get_live_price

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
    except:
        pass

# ── 持仓周期 ──
HOLD_DAYS = 20          # 每笔持有20个交易日
HARD_STOP = -12.0       # 硬止损-12%
TARGET_EXIT_DAYS = 5    # 达目标价后至少持有5天再卖
SCORE_DROP_DAYS = 10    # 评分连降10天+跌破成本→清仓
SCORE_DROP_THRESHOLD = 55  # 跌破此评分且连降SCORE_DROP_DAYS天

# ── 评分对应仓位 ──
POSITION_SCALE = [
    (45, 0.15, '高置信15%'),
    (35, 0.10, '中置信10%'),
    (30, 0.05, '低置信5%'),
    (0,  0.00, '不建仓'),
]

# ── 买入条件阈值 ──
MIN_SCORE = 30          # 评分≥30才考虑买入
MAX_PX_DEV = 0.095      # 非涨跌停(<9.5%)
MAX_MARKET_DROP = 1.5   # 大盘非大跌日(上证跌<1.5%)
MAX_PER_INDUSTRY = 2    # 单行业不超过2只

# ── 路径缓存 ──
POS_LOG_PATH = BASE / '.risk_position_log.json'

def login():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def get(op, path):
    return json.loads(op.open(Request(f'{TRADE_URL}{path}')).read())

def post(op, path, data):
    return json.loads(op.open(Request(f'{TRADE_URL}{path}',
        data=json.dumps(data).encode(),
        headers={'Content-Type':'application/json'})).read())

def parse_float(v, default=0.0):
    try: return float(v)
    except: return default

def get_industry(code):
    """查stock_info表获取行业"""
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        r = conn.execute(f"SELECT industry FROM stock_info WHERE stock_code='{code}'").fetchone()
        conn.close()
        if r and r[0] and len(r[0]) >= 3:
            return r[0][:3]
    except: pass
    return 'ZZZ'

def get_market_status():
    """检查当日大盘状态"""
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        row = conn.execute("""
            SELECT close, change_pct FROM index_daily
            WHERE index_code='000001' ORDER BY date DESC LIMIT 1
        """).fetchone()
        conn.close()
        if row:
            chg = parse_float(row[1], 0)
            idx = parse_float(row[0], 0)
            return chg, idx
    except: pass
    return 0, 0

def get_score_distribution():
    """从simulate获取当前全部持仓的评分"""
    try:
        data = get(login(), '/api/holdings')
        return {p['code']: p for p in data.get('positions', [])}
    except: return {}

def calc_position_pct(score, market_chg):
    """评分对应仓位 × 大盘系数"""
    base = 0
    label = '不建仓'
    for threshold, pct, desc in POSITION_SCALE:
        if score >= threshold:
            base, label = pct, desc
            break
    # 大盘系数：跌超1%打8折，跌超1.5%不打
    mkt_coef = 1.0
    if market_chg < -1.0:
        mkt_coef = 0.8
    return base * mkt_coef, label

def load_position_log():
    if POS_LOG_PATH.exists():
        try: return json.loads(POS_LOG_PATH.read_text())
        except: pass
    return {}

def save_position_log(log):
    POS_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2))

def calc_holding_days(buy_date_str):
    """计算持仓天数（按交易日）"""
    if not buy_date_str: return 0
    try:
        buy_date = datetime.strptime(buy_date_str[:10], '%Y-%m-%d').date()
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        cnt = conn.execute(f"""
            SELECT COUNT(*) FROM index_daily
            WHERE index_code='000001' AND date >= '{buy_date}' AND date <= '{date.today()}'
        """).fetchone()[0]
        conn.close()
        return cnt if cnt else 0
    except: return 0

def check_sell_conditions(code, pos, pos_log, market_chg, scores_map):
    """检查5层卖出规则，返回 (action, reason) 或 None"""
    cost = parse_float(pos.get('avg_cost'), 0)
    shares = pos.get('shares', 0)
    if shares == 0 or cost == 0:
        return None

    pr, chg = get_live_price(code)
    if not pr:
        return None
    pnl = (pr / cost - 1) * 100

    buy_date = pos_log.get(code, {}).get('buy_date', '')
    hold_days = calc_holding_days(buy_date)
    score_entry = scores_map.get(code, {})
    current_score = parse_float(score_entry.get('v5_score', score_entry.get('final_score', 0)), 0)

    # ── 规则1: 硬止损-12%（立即执行）──
    if pnl <= HARD_STOP:
        return ('清仓', f'硬止损{pnl:.1f}%')

    # ── 规则2: 达目标价+持仓≥5天──
    target = parse_float(pos.get('target', 0), 0)
    if target > 0 and pr >= target and hold_days >= TARGET_EXIT_DAYS:
        return ('清仓', f'达目标价{target:.2f}')

    # ── 规则3: 持仓满20天+评分<30──
    if hold_days >= HOLD_DAYS and current_score < MIN_SCORE:
        return ('清仓', f'满{HOLD_DAYS}天评分{current_score:.0f}<{MIN_SCORE}')

    # ── 规则4: 评分连降+跌破成本（存历史评分做趋势判断）──
    score_history = pos_log.get(code, {}).get('scores', [])
    if len(score_history) >= SCORE_DROP_DAYS:
        recent = score_history[-SCORE_DROP_DAYS:]
        if all(recent[i] >= recent[i+1] for i in range(len(recent)-1)):
            if pnl < 0:
                return ('清仓', f'评分连降{SCORE_DROP_DAYS}天+跌破成本')

    # ── 规则5: Agent风控技术破位/目标减仓 + 评分不看好 ──
    if current_score < 35 or pnl < 0:
        try:
            _risk_path = BASE / 'risk_signals.json'
            if _risk_path.exists():
                _rd = json.loads(_risk_path.read_text())
                for _sig in _rd.get('signals', []):
                    if _sig['code'] == code and _sig['action'] == '清仓':
                        return ('清仓', f"Agent技术破位: {_sig.get('reason','')}")
                    if _sig['code'] == code and _sig['action'] == '减半仓':
                        return ('减半仓', f"Agent目标减仓: {_sig.get('reason','')}")
        except:
            pass

    return None

def check_buy_conditions(code, score_entry, holdings, industry_counts, market_chg):
    """检查5条买入条件，返回 (ok, reason)"""
    score = parse_float(score_entry.get('v5_score', score_entry.get('final_score', 0)), 0)

    # 条件1: 评分≥30
    if score < MIN_SCORE:
        return False, f'评分{score:.0f}<{MIN_SCORE}'

    # 行业集中度
    ind = get_industry(code)
    if industry_counts.get(ind, 0) >= MAX_PER_INDUSTRY:
        return False, f'{ind}行业已{industry_counts[ind]}只≥{MAX_PER_INDUSTRY}'

    # 获取实时价格和涨跌幅
    pr, chg = get_live_price(code)
    if not pr:
        return False, '获取价格失败'

    # 条件2: 价格在预设介入区间内
    entry_low = parse_float(score_entry.get('entry_low', 0), 0)
    entry_high = parse_float(score_entry.get('entry_high', 0), 0)
    if entry_low > 0 and entry_high > 0:
        if not (entry_low <= pr <= entry_high):
            return False, f'价格{pr:.2f}不在介入区间[{entry_low:.2f},{entry_high:.2f}]'

    # 条件3: 非涨跌停
    if abs(chg) >= 9.5:
        return False, f'涨跌幅{chg:+.1f}%≥9.5%'

    # 条件4: MA5 > MA10
    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        rows = conn.execute(f"""
            SELECT close FROM stock_daily WHERE stock_code='{code}'
            ORDER BY date DESC LIMIT 10
        """).fetchall()
        conn.close()
        closes = [float(r[0]) for r in rows][::-1]
        if len(closes) >= 10:
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes) / 10
            if ma5 <= ma10:
                return False, f'MA5({ma5:.2f})≤MA10({ma10:.2f})下跌趋势'
    except: pass

    # 条件5: 大盘非大跌日
    mkt_chg, mkt_idx = get_market_status()
    if mkt_chg is not None and mkt_chg < -MAX_MARKET_DROP:
        return False, f'大盘跌{mkt_chg:+.1f}%<{-MAX_MARKET_DROP}%'

    return True, 'ok'

def get_position_sizing(cash, score, market_chg):
    """计算买入股数"""
    pct, label = calc_position_pct(score, market_chg)
    max_amt = cash * pct
    # 实际投入：不超过账户总资产的对应比例
    max_amt = min(max_amt, INITIAL_CAPITAL * pct)
    shares = max(int(max_amt / 100) * 100, 100)  # 整手
    return shares, label

def main():
    today = str(date.today())
    now = datetime.now()
    hour = now.hour

    # 非交易时段跳过
    if not (9 <= hour < 11 or 13 <= hour < 15):
        return

    # 检查大盘是否大跌
    mkt_chg, mkt_idx = get_market_status()
    if mkt_chg is not None and mkt_chg < -MAX_MARKET_DROP:
        print(f"大盘跌{mkt_chg:+.1f}%，超过{-MAX_MARKET_DROP}%，仅执行止损不清仓")
        # 大盘暴跌日只止损，不开新仓
    else:
        print(f"大盘{mkt_chg:+.1f}%" if mkt_chg is not None else "大盘数据获取失败")

    op = login()
    scores_map = get_score_distribution()

    # ── 获取当前持仓 ──
    st = get(op, '/api/status')
    cash = st.get('cash', 0)
    positions = st.get('positions', [])
    held_map = {p['code']: p for p in positions}

    # 加载持仓日志（记录买入日期、评分历史）
    pos_log = load_position_log()
    today_stamp = today

    # ── 行业计数 ──
    industry_counts = {}
    for p in positions:
        ind = get_industry(p['code'])
        industry_counts[ind] = industry_counts.get(ind, 0) + 1

    print(f"\n持仓{len(positions)}只 | 现金{cash:,.0f} | {today}")

    # ═══════════════════════════════════
    # 卖出检查
    # ═══════════════════════════════════
    executed_sells = []
    for p in positions:
        code = p['code']
        result = check_sell_conditions(code, p, pos_log, mkt_chg, scores_map)
        if result:
            action, reason = result
            # 大盘暴跌日只执行硬止损
            if mkt_chg is not None and mkt_chg < -MAX_MARKET_DROP:
                if action == '清仓' and '硬止损' not in reason:
                    print(f"  ⏭ {code} {p.get('name','')} 大盘暴跌，跳过: {reason}")
                    continue
            trade_shares = p.get('shares', 0)
            if action == '减半仓':
                trade_shares = max(100, trade_shares // 2)
            r = post(op, '/api/trade', {'action':'sell','code':code,'shares':trade_shares})
            if r.get('ok'):
                act_label = '减半' if action == '减半仓' else '清仓'
                print(f"  {'✂️' if action=='减半仓' else '💀'} {code} {p.get('name','')} {reason} ✅")
                notify_qq(act_label, code, p.get('name',''), p.get('current_price',0),
                          trade_shares, reason, pnl=p.get('pnl_pct',0))
                executed_sells.append(code)
                # 更新日志
                pl = pos_log.get(code, {})
                pl['exit_date'] = today_stamp
                pl['exit_reason'] = reason
                pl['pnl'] = p.get('pnl_pct', 0)
                pos_log[code] = pl
            else:
                print(f"  ❌ {code} {reason} 执行失败: {r.get('msg','')}")

    # 更新评分历史
    for p in positions:
        code = p['code']
        score_entry = scores_map.get(code, {})
        score = parse_float(score_entry.get('v5_score', score_entry.get('final_score', 0)), 0)
        if code not in pos_log:
            pos_log[code] = {'buy_date': p.get('buy_date', today_stamp), 'scores': []}
        if 'scores' not in pos_log[code]:
            pos_log[code]['scores'] = []
        pos_log[code]['scores'].append(score)
        # 只保留最近30天的评分
        if len(pos_log[code]['scores']) > 30:
            pos_log[code]['scores'] = pos_log[code]['scores'][-30:]

    # ═══════════════════════════════════
    # 买入检查（大盘暴跌日不买）
    # ═══════════════════════════════════
    if mkt_chg is not None and mkt_chg < -MAX_MARKET_DROP:
        print("大盘暴跌，不执行买入")
    else:
        # 获取观察池（watch_active）
        watch_data = get(op, '/api/holdings')
        watch_stocks = [p for p in watch_data.get('positions', [])
                       if p.get('status') in ('watch_active',)
                       and p['code'] not in held_map
                       and p['code'] not in executed_sells]

        if watch_stocks:
            # 筛选符合条件的
            candidates = []
            for s in watch_stocks:
                ok, reason = check_buy_conditions(s['code'], s, positions, industry_counts, mkt_chg)
                if ok:
                    candidates.append(s)
                else:
                    print(f"  ⏭ {s['code']} {s.get('name','')} {reason}")

            # 按评分排序，取评分最高的
            candidates.sort(key=lambda x: -parse_float(
                x.get('v5_score', x.get('final_score', 0)), 0))

            # 计算可用仓位
            slots_used = len(positions)
            n_positions = len(positions) - len(executed_sells) + len(candidates)  # 预估
            max_new = 5 - n_positions if n_positions < 5 else 0
            candidates = candidates[:max_new]

            for s in candidates:
                code = s['code']
                score = parse_float(s.get('v5_score', s.get('final_score', 0)), 0)
                shares, label = get_position_sizing(cash, score, mkt_chg or 0)
                if shares < 100 or cash < shares * 10:
                    continue

                pr, _ = get_live_price(code)
                if not pr:
                    continue

                r = post(op, '/api/trade', {
                    'action': 'buy',
                    'code': code,
                    'name': s.get('name', ''),
                    'price': pr,
                    'shares': shares,
                })
                if r.get('ok'):
                    pos_log[code] = {
                        'buy_date': today_stamp,
                        'scores': [score],
                        'buy_price': pr,
                        'intended_pct': label,
                    }
                    notify_qq('买入', code, s.get('name',''), pr, shares, f'{label} 评分{score:.0f}')
                    # 更新行业计数
                    ind = get_industry(code)
                    industry_counts[ind] = industry_counts.get(ind, 0) + 1
                    cash -= shares * pr
                    print(f"  📈 {code} {s.get('name','')} {label} {shares}股 ✅")
                else:
                    print(f"  ❌ {code} {s.get('name','')} 买入失败: {r.get('msg','')}")
                time.sleep(0.5)

    # 保存日志
    save_position_log(pos_log)
    print("done")

if __name__ == '__main__':
    main()
