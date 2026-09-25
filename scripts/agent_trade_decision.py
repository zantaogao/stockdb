#!/usr/bin/env python3
"""Agent全权账户（agent_auto）交易决策执行器（2026-09-04 用户拍板建立）

账户语义（与机械账户的区别）：
- 100 万真钱语义（账本记账=指令成交价，券商端由用户镜像执行）
- agent 全权买卖：不挂主账户风控、不走机械 rebalance；
  每天 cron 唤起 agent → --context 拉决策上下文 → agent 写订单 JSON → --apply 落账
- 只保留三条硬编码防抽风护栏（超限拒单）：单笔买入 ≤15万 / 单日订单 ≤5笔 / 单日买入总额 ≤30万
- 大跌市（中证1000 尾盘确认≤-3% 或早盘急跌≤-3%且低于开盘）只卖不买（沿用主系统 08-18 拍板口径）

信号源与 center_dual 同款：0.5*pct(fusion_center) + 0.5*pct(fusion_score)，候选池取前 15。

用法:
  python3 -B scripts/agent_trade_decision.py --context              # 决策上下文 JSON（信号/持仓/大盘/护栏余量）
  python3 -B scripts/agent_trade_decision.py --apply orders.json    # 执行订单（校验+落账+QQ推送）
  python3 -B scripts/agent_trade_decision.py --review               # 统计复盘（胜率/盈亏比/夏普/对比 center_dual）

orders.json 格式: [{"action":"BUY","code":"600xxx","shares":1000,"reason":"..."},
                   {"action":"SELL","code":"000xxx","shares":0,"reason":"..."}]  # SELL shares=0/省略=清仓

纪律（agent 决策依据，写在这供 cron prompt 引用，非硬编码）：
  买: 候选池前15内挑；剔近3日累计≤-4%接刀位/当日涨幅≥7%(R2不追高)；单票≤15%仓位；目标持仓8-15只
  卖: -8%硬止损；峰值回撤8%止盈(峰值需≥成本+5%)；信号跌出候选池且浮亏→次日出；持有20交易日<+5%时间止损
"""
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import numpy as np
import duckdb
from core.unified_account import AccountStore
from core.prices import fetch_prices_batch, fetch_price_live
from core.trading_time import in_trading_session

STATE_DB = BASE / 'ledger.db'
SIGNALS_DB = BASE / 'signals.db'
TUSHARE_DB = BASE / 'tushare.db'
ACCOUNT_ID = 'agent_auto'
ACCOUNT_NAME = 'Agent全权'

# ── 防抽风护栏（硬编码上限，唯一"风控"；超限拒单并打印原因）──
MAX_SINGLE_BUY = 150_000.0
MAX_DAILY_ORDERS = 5
MAX_DAILY_BUY_TOTAL = 300_000.0


def _conn():
    c = sqlite3.connect(str(STATE_DB), timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("ATTACH DATABASE ? AS sig", (str(SIGNALS_DB),))
    return c


def _tushare():
    return duckdb.connect(str(TUSHARE_DB), read_only=True)


def candidate_pool(state, d, top_n=15):
    """center_dual 同款合成分，取前 top_n（裸码, 分数, 中枢分, 三模型分）"""
    ct = {r[0]: float(r[1]) for r in state.execute(
        "SELECT stock_code, score FROM sig.fusion_center_signals "
        "WHERE REPLACE(date,'-','')=? AND score IS NOT NULL", (d,)).fetchall()}
    md = {r[0]: float(r[1]) for r in state.execute(
        "SELECT stock_code, fusion_score FROM sig.signal_history "
        "WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL", (d,)).fetchall()}
    common = sorted(set(ct) & set(md))
    if not common:
        return []
    n = len(common)
    ct_rank = np.argsort(np.argsort([ct[c] for c in common])) + 1
    md_rank = np.argsort(np.argsort([md[c] for c in common])) + 1
    comb = {c: 0.5 * ct_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
            for i, c in enumerate(common)}
    picks = sorted(comb.items(), key=lambda x: -x[1])[:top_n]
    return [{'code': c, 'combo_score': round(s, 2),
             'center_score': round(ct[c], 4), 'model_score': round(md[c], 4)}
            for c, s in picks]


def market_state(state, tdu):
    out = {}
    try:
        px, chg = fetch_price_live('000852')
        out['zz1000_ret'] = round(chg, 2) if px else None
    except Exception:
        out['zz1000_ret'] = None
    try:
        r = state.execute("SELECT crash_date FROM strategy_crash_state ORDER BY rowid DESC LIMIT 1").fetchone()
        out['last_crash_date'] = r[0] if r else None
    except Exception:
        out['last_crash_date'] = None
    try:
        rows = tdu.execute(
            "SELECT close FROM (SELECT trade_date, close, "
            "ROW_NUMBER() OVER (ORDER BY trade_date DESC) rn "
            "FROM daily WHERE ts_code LIKE '000852.%') WHERE rn<=4 ORDER BY trade_date").fetchall()
        closes = [float(r[0]) for r in rows]
        out['zz1000_3d_ret'] = round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) >= 4 else None
    except Exception:
        out['zz1000_3d_ret'] = None
    return out


def context():
    state, tdu = _conn(), _tushare()
    now = datetime.now()
    today = now.strftime('%Y%m%d')
    d = state.execute(
        "SELECT MAX(REPLACE(date,'-','')) FROM sig.fusion_center_signals WHERE REPLACE(date,'-','') < ?",
        (today,)).fetchone()[0]
    store = AccountStore()
    acct = store.load(ACCOUNT_ID)
    pool = candidate_pool(state, d)
    # 持仓实时价 + 浮盈/持有天数
    codes = [p.code for p in acct.positions]
    rtp = fetch_prices_batch(codes) if codes else {}
    # 2026-09-15 修复：峰值跟踪。此前 strategy_positions.peak_price 自建仓起从不更新
    # （全等于 avg_cost），纪律②"峰值≥成本+5%且回撤≥8%"因而永不触发。此后每次决策
    # 上下文以实时价刷新峰值（同 strategy_accounts_daily.py:699 口径 peak=max(peak,现价)）。
    _peak_upd = False
    for _p in acct.positions:
        _px = rtp.get(_p.code)
        if _px and _px > (_p.peak_price or 0):
            _p.peak_price = round(_px, 3)
            _peak_upd = True
    if _peak_upd:
        try:
            store.save(acct)
        except Exception as _e:
            sys.stderr.write(f'[peak] 峰值落库失败(不影响决策): {_e}\n')
    held = []

    for p in acct.positions:
        px = rtp.get(p.code) or p.avg_cost
        try:
            hd = tdu.execute("SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ? AND trade_date <= ?",
                             (str(p.buy_date).replace('-', ''), today)).fetchone()[0]
        except Exception:
            hd = None
        held.append({'code': p.code, 'name': p.name, 'shares': p.shares,
                     'avg_cost': p.avg_cost, 'price': px,
                     'pnl_pct': round((px / p.avg_cost - 1) * 100, 2) if p.avg_cost else None,
                     'peak': p.peak_price,
                     'peak_drawdown_pct': round((px / p.peak_price - 1) * 100, 2) if p.peak_price else None,
                     'hold_days': int(hd or 0)})
    # 护栏今日余量
    td_dash = now.strftime('%Y-%m-%d')
    row = state.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN direction='BUY' THEN amount ELSE 0 END),0) "
        "FROM trade_log WHERE strategy=? AND trade_date=?", (ACCOUNT_ID, td_dash)).fetchone()
    n_today, buy_today = int(row[0] or 0), float(row[1] or 0)
    # 近5日 NAV
    navs = state.execute(
        "SELECT date, nav, daily_ret, market_ret FROM strategy_accounts "
        "WHERE account_id=? ORDER BY date DESC LIMIT 5", (ACCOUNT_ID,)).fetchall()
    json.dump({
        'as_of': now.strftime('%F %T'),
        'signal_date': d,
        'market': market_state(state, tdu),
        'cash': round(acct.cash, 2),
        'guard_remaining': {'orders': MAX_DAILY_ORDERS - n_today,
                            'buy_total': round(MAX_DAILY_BUY_TOTAL - buy_today, 2),
                            'single_max': MAX_SINGLE_BUY},
        'positions': held,
        'candidates': pool,
        'nav_recent': [{'date': r[0], 'nav': r[1], 'ret': r[2], 'mkt': r[3]} for r in reversed(navs)],
    }, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write('\n')
    state.close(); tdu.close()


def apply(orders_file):
    if not in_trading_session():
        print('❌ 非交易时段，拒绝执行（9:30-11:30/13:00-15:00）')
        sys.exit(2)
    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：非交易日拒绝落账
    from core.trade_calendar import is_trading_day
    if not is_trading_day():
        print('🚫 非交易日（tushare trade_cal 权威），拒绝执行')
        sys.exit(0)
    orders = json.loads(Path(orders_file).read_text())
    state, tdu = _conn(), _tushare()
    now = datetime.now()
    today, td_dash, now_ts = now.strftime('%Y%m%d'), now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S')
    if len(orders) > MAX_DAILY_ORDERS:
        print(f'❌ 本批 {len(orders)} 笔 > 单日 {MAX_DAILY_ORDERS} 笔上限，整批拒绝')
        sys.exit(2)
    row = state.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN direction='BUY' THEN amount ELSE 0 END),0) "
        "FROM trade_log WHERE strategy=? AND trade_date=?", (ACCOUNT_ID, td_dash)).fetchone()
    n_used, buy_used = int(row[0] or 0), float(row[1] or 0)
    # 大跌市判定：昨日确认未收复 或 早盘急跌（≤-3% 且现价≤昨收=持续走弱）
    ms = market_state(state, tdu)
    crash_block_buy = False
    if ms.get('last_crash_date') and ms.get('zz1000_ret') is not None and ms['zz1000_ret'] <= -1.5:
        crash_block_buy = True
    if (ms.get('zz1000_ret') or 0) <= -3.0:
        crash_block_buy = True
    if crash_block_buy:
        print(f'🛑 大跌市状态，本批只可卖（zz1000 {ms.get("zz1000_ret")}%，昨日crash {ms.get("last_crash_date")}）')

    store = AccountStore()
    acct = store.load(ACCOUNT_ID)
    held = {p.code: p for p in acct.positions}
    all_codes = list({*held.keys(), *(o['code'] for o in orders)})
    rtp = fetch_prices_batch(all_codes)
    # 2026-09-15 修复：峰值跟踪（同 context()，apply 末尾统一 store.save）
    for _p in acct.positions:
        _px = rtp.get(_p.code)
        if _px and _px > (_p.peak_price or 0):
            _p.peak_price = round(_px, 3)
    # 昨收（R2 不追高用）
    prev_map = {}
    try:
        for r in tdu.execute("SELECT ts_code, close FROM daily WHERE trade_date=(SELECT MAX(trade_date) FROM daily)").fetchall():
            prev_map[r[0].split('.')[0]] = float(r[1])
    except Exception:
        pass

    ok, failed = [], []
    for o in orders:
        code, act, reason = o['code'], o['action'].upper(), o.get('reason', '')[:200]
        px = rtp.get(code)
        if not px or px <= 0:
            failed.append((code, act, '无实时价(停牌?)')); continue
        if act == 'BUY':
            shares = int(o.get('shares', 0))
            cost = shares * px
            if cost > MAX_SINGLE_BUY:
                failed.append((code, act, f'单笔{cost:,.0f} > {MAX_SINGLE_BUY:,.0f} 护栏')); continue
            if buy_used + cost > MAX_DAILY_BUY_TOTAL:
                failed.append((code, act, f'日买入累计将超 {MAX_DAILY_BUY_TOTAL:,.0f} 护栏')); continue
            if crash_block_buy:
                failed.append((code, act, '大跌市只卖不买')); continue
            if shares < 100 or (code[:2] in ('30', '68') and shares < 200):
                failed.append((code, act, f'{shares}股低于最低申报')); continue
            if prev_map.get(code) and px / prev_map[code] - 1 >= 0.07:
                failed.append((code, act, 'R2不追高(较昨收≥7%)')); continue
            if cost > acct.cash:
                failed.append((code, act, f'现金不足(需{cost:,.0f}/有{acct.cash:,.0f})')); continue
            name = o.get('name') or ''
            try:
                r = tdu.execute("SELECT name FROM stock_basic WHERE ts_code LIKE ?", (code + '.%',)).fetchone()
                if r and r[0]:
                    name = r[0]
            except Exception:
                pass
            acct.cash -= cost
            pos = held.get(code)
            if pos:
                tot = pos.shares + shares
                acct.remove_position(code)
                from core.unified_account import Position
                acct.add_position(Position(
                    code=code, name=name, shares=tot,
                    avg_cost=round((pos.avg_cost * pos.shares + cost) / tot, 4),
                    buy_date=pos.buy_date, peak_price=round(max(pos.peak_price or px, px), 3),
                    stop_loss=round(min(pos.stop_loss or px * 0.92, px * 0.92), 3), target=0))
            else:
                from core.unified_account import Position
                acct.add_position(Position(
                    code=code, name=name, shares=shares, avg_cost=round(px, 3),
                    buy_date=today, peak_price=round(px, 3),
                    stop_loss=round(px * 0.92, 3), target=0))
                held[code] = acct.positions[-1]
            acct.trades.append({'date': td_dash, 'action': '买入', 'code': code, 'name': name,
                                'price': round(px, 3), 'shares': shares, 'amount': round(cost, 2),
                                'reason': f'[agent裁决] {reason}', 'trade_time': now_ts})
            _log(state, code, name, 'BUY', px, shares, cost, reason)
            buy_used += cost; n_used += 1
            ok.append(f'🟢买 {code} {name} {shares}股 @{px:.2f} {cost:,.0f} | {reason}')
        elif act == 'SELL':
            pos = held.get(code)
            if not pos or pos.shares <= 0:
                failed.append((code, act, '无持仓')); continue
            if str(pos.buy_date) == today:
                failed.append((code, act, 'T+1当日买入不可卖')); continue
            shares = int(o.get('shares', 0)) or pos.shares
            if shares > pos.shares:
                shares = pos.shares
            if (code[:2] in ('30', '68')) and shares < 200 and shares != pos.shares:
                failed.append((code, act, '科创/创业部分卖<200股')); continue
            revenue = shares * px
            pnl_pct = round((px / pos.avg_cost - 1) * 100, 2) if pos.avg_cost else None
            acct.cash += revenue
            if shares >= pos.shares:
                acct.remove_position(code)
                held.pop(code, None)
            else:
                acct.remove_position(code)
                from core.unified_account import Position
                acct.add_position(Position(
                    code=code, name=pos.name, shares=pos.shares - shares, avg_cost=pos.avg_cost,
                    buy_date=pos.buy_date, peak_price=pos.peak_price,
                    stop_loss=pos.stop_loss, target=0))
            acct.trades.append({'date': td_dash, 'action': '卖出', 'code': code, 'name': pos.name,
                                'price': round(px, 3), 'shares': shares, 'amount': round(revenue, 2),
                                'pnl_pct': pnl_pct, 'reason': f'[agent裁决] {reason}', 'trade_time': now_ts})
            _log(state, code, pos.name, 'SELL', px, shares, revenue, reason, pnl_pct)
            n_used += 1
            ok.append(f'🔴卖 {code} {pos.name} {shares}股 @{px:.2f} 收益{revenue:,.0f} ({pnl_pct:+.2f}%) | {reason}')
        else:
            failed.append((code, act, 'action 须 BUY/SELL'))

    # ── NAV 估值落库（照 strategy_accounts_daily manual 分支同口径）──
    rtp2 = fetch_prices_batch([p.code for p in acct.positions]) if acct.positions else {}
    pos_val = sum(p.shares * (rtp2.get(p.code) or p.avg_cost) for p in acct.positions)
    nav = acct.cash + pos_val
    prev_hist = [h for h in acct.nav_history if str(h.get('date', '')).replace('-', '') != today]
    prev = prev_hist[-1].get('nav') if prev_hist else acct.initial_capital
    daily_ret = round((nav / prev - 1) * 100, 4) if prev > 0 else 0.0
    acct.record_nav(rtp2)
    store.save(acct)
    if abs(daily_ret) <= 30:
        state.execute("""
            INSERT OR REPLACE INTO strategy_accounts
            (account_id, date, nav, cash, pos_value, daily_ret, market_ret, n_pos)
            VALUES (?,?,?,?,?,?,?,?)""",
            (ACCOUNT_ID, today, round(nav, 2), round(acct.cash, 2), round(pos_val, 2),
             daily_ret, ms.get('zz1000_ret'), len(acct.positions)))
        state.commit()
    state.close(); tdu.close()

    print('\n'.join(ok) or '(本批无成交)')
    for c, a, w in failed:
        print(f'⛔ 拒单 {c} {a}: {w}')
    print(f'账户: 现金{acct.cash:,.0f} + 市值{pos_val:,.0f} = NAV {nav:,.2f} ({daily_ret:+.2f}%) 持仓{len(acct.positions)}只')

    # 成交即时推送（串行锁在 notify_trade 内部）
    for line_o in ok:
        try:
            seg = line_o.split()
            action = 'BUY' if line_o.startswith('🟢') else 'SELL'
            code = seg[1]
            name = seg[2]
            shares = int(seg[3].replace('股', ''))
            price = float(seg[4].replace('@', ''))
            amount = seg[5]
            amt = float(amount.replace(',', '').replace('收益', '').replace('金额', '').replace('花费', ''))
            reason_txt = line_o.split('| ', 1)[1] if '| ' in line_o else ''
            # 2026-09-14 卖出推送带盈亏：ok 行格式 "收益{revenue} ({pnl_pct}%)" → "盈亏幅度 (收益额)"
            pnl_txt = ''
            try:
                if action == 'SELL':
                    _seg = line_o.split('收益', 1)[1]
                    _rev = _seg.split(' ')[0]
                    _pct = _seg[_seg.index('(') + 1:_seg.index(')')]
                    pnl_txt = f"{_pct} (收益{_rev}元)"
            except Exception:
                pass
            subprocess.Popen(
                [sys.executable, '-B', str(BASE / 'scripts' / 'notify_trade.py'),
                 ACCOUNT_NAME, action, code, name, str(shares), str(price), str(amt), reason_txt, pnl_txt],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f'  [push] 解析失败: {e} | {line_o[:60]}')
    if failed:
        sys.exit(1)


def _log(state, code, name, direction, px, shares, amount, reason, pnl_pct=None):
    max_id = state.execute("SELECT MAX(id) FROM trade_log").fetchone()[0] or 0
    state.execute("""
        INSERT INTO trade_log
        (id, code, name, direction, price, quantity, amount, trade_date, trade_time,
         strategy, signal_score, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (max_id + 1, code, name, direction, round(float(px), 4), int(shares),
         round(float(amount), 4), datetime.now().strftime('%Y-%m-%d'),
         datetime.now().strftime('%H:%M:%S'), ACCOUNT_ID, None,
         f'[agent全权] {reason}' + (f' | pnl {pnl_pct}%' if pnl_pct is not None else '')))
    state.commit()  # 立即提交，防挂起写事务（同 strategy_accounts_daily 08-28 修复）


def review():
    """统计复盘：胜率/盈亏比/持有分布/夏普 + vs center_dual 同窗对比"""
    state, tdu = _conn(), _tushare()
    trades = state.execute(
        "SELECT direction, trade_date, trade_time, code, price, quantity, amount, notes "
        "FROM trade_log WHERE strategy=? ORDER BY trade_date, trade_time", (ACCOUNT_ID,)).fetchall()
    sells = [t for t in trades if t[0] == 'SELL']
    pnls = []
    for t in sells:
        try:
            pnls.append(float(t[7].split('pnl ')[1].rstrip('%')))
        except Exception:
            pass
    navs = state.execute(
        "SELECT date, nav, daily_ret, market_ret FROM strategy_accounts WHERE account_id=? ORDER BY date",
        (ACCOUNT_ID,)).fetchall()
    cd = state.execute(
        "SELECT date, nav FROM strategy_accounts WHERE account_id='center_dual' ORDER BY date").fetchall()
    rets = [r[2] for r in navs if r[2] is not None][1:]  # 首日建仓日不算
    sharpe = None
    if len(rets) >= 5:
        r = np.array(rets, dtype=float) / 100
        sharpe = round(float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(242)), 2) if np.std(r, ddof=1) > 0 else None
    total = (navs[-1][1] / 1_000_000 - 1) * 100 if navs else 0
    # 同窗对比：两账户共同起始日→今天
    common = [d for d in {r[0] for r in navs} & {r[0] for r in cd}]
    cd_same = ''
    if common and len(navs) > 1:
        start = min(common)
        base_self = next(r[1] for r in navs if r[0] == start)
        base_cd = next(r[1] for r in cd if r[0] == start)
        cd_same = round((cd[-1][1] / base_cd - 1) * 100, 2) if cd else None
        total = round((navs[-1][1] / base_self - 1) * 100, 2)
    print(json.dumps({
        'account': ACCOUNT_NAME, 'as_of': datetime.now().strftime('%F %T'),
        'nav': navs[-1][1] if navs else 1_000_000, 'total_return_pct': total,
        'center_dual_same_window_pct': cd_same,
        'trades_total': len(trades), 'sells_closed': len(sells),
        'win_rate_pct': round(len([p for p in pnls if p > 0]) / len(pnls) * 100, 1) if pnls else None,
        'avg_win_pct': round(np.mean([p for p in pnls if p > 0]), 2) if any(p > 0 for p in pnls) else None,
        'avg_loss_pct': round(np.mean([p for p in pnls if p <= 0]), 2) if any(p <= 0 for p in pnls) else None,
        'payoff_ratio': round(abs(np.mean([p for p in pnls if p > 0]) / np.mean([p for p in pnls if p <= 0])), 2)
            if any(p > 0 for p in pnls) and any(p <= 0 for p in pnls) and np.mean([p for p in pnls if p <= 0]) != 0 else None,
        'sharpe_annualized(242d)': sharpe,
        'nav_days': len(navs),
    }, ensure_ascii=False, indent=1))
    state.close(); tdu.close()


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] == '--context':
        context()
    elif a[0] == '--apply' and len(a) > 1:
        apply(a[1])
    elif a[0] == '--review':
        review()
    else:
        print(__doc__)
        sys.exit(2)