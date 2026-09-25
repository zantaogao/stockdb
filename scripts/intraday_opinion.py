#!/usr/bin/env python3
"""盘中意见层 — 实时价格监控 + 意见生成（2026-08-30 上线）。

每 10 分钟由 cron 调起（只读咨询，不写 pending.json、不下单）：
  1. 读 analysis/opinion_universe.json（夜间 22:15 生成的关注池）
  2. Sina 批量实时价（一次请求拉全部 170 只）
  3. 规则引擎对每只出意见，只保留【本轮新触发】的（当天同票同类型不重复推）
  4. 新意见 → 合并成一条 QQ 消息推主人通道 + 追加 analysis/opinion_log.jsonl（面板留档）

意见规则：
  买入候选（名单票）:
    🟢 建议买入   现价 <= 信号日收盘*1.02 且 未触停买线（跌≤-3%时早盘缓/提示）；双名单共振加 ⭐
    ⚠️ 追高提示   现价 > 信号日收盘*1.05 → 等回落
    ⛔ 停买区     现价较信号日收盘跌超 -3% → 与执行端四层保护同口径，提示系统会缓/停
  持仓（主账户+策略账户）:
    🔴 触及止损   现价 <= 执行止损线 = min(扫描止损, 成本×0.94)（2026-09-15 对齐执行端 R4 口径，
                   intraday_decision.py:74 FLOAT_STOP_FLOOR；此前用扫描线导致误报，0915 午间报告实锤）
    🟠 逼近止损   现价 <= 执行止损线*1.01
    🎯 触及目标   现价 >= target（主账户 target_price）
    🟡 回撤止盈   峰值≥成本×1.05 且 现价≤峰值×0.92（执行端 R3 条件2项已满足）：
                   大盘≤-2% → 🔴级"已触发，执行端将卖出"；否则 🟡级"待触发引信"（2026-09-15 补漏报，
                   峰值读 ledger.db position_peaks 实时值，口径同 intraday_decision.py:84-85）
用法: /usr/bin/python3 -B scripts/intraday_opinion.py [--dry]
"""
import json
import subprocess
import sys
import time
import fcntl
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from core.prices import fetch_prices_batch

DRY = '--dry' in sys.argv
ANALYSIS = BASE / 'analysis'
UNIVERSE = ANALYSIS / 'opinion_universe.json'
STATE = ANALYSIS / 'opinion_state.json'
LOG = ANALYSIS / 'opinion_log.jsonl'
PUSH_LOCK = '/tmp/opinion_push.lock'
QQ_TARGET = 'qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616'
LEDGER = BASE / 'ledger.db'
# 执行端口径常量（2026-09-15 对齐 intraday_decision.py，改那边要同步这边）
FLOAT_STOP_FLOOR = 0.94           # R4: 执行止损 = min(扫描线, 成本×0.94)
DRAWDOWN_MIN_GAIN = 1.05          # R3: 峰值≥成本×1.05
DRAWDOWN_RATIO = 0.92             # R3: 现价≤峰值×0.92
DRAWDOWN_MARKET_THRESHOLD = -2.0  # R3: 当日大盘≤-2% 才实际触发卖出


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return default


def load_peaks():
    """持仓峰值 {裸码: peak}（只读，口径同执行端）：主账户 ledger.db.position_peaks
    + 策略账户 strategy_positions.peak_price 按 code 取大。读不到返回 {}（R3 意见静默跳过）。
    2026-09-15：09-15 前策略账户 peak 从不更新（全=成本），当日起 exec/decision 已修，值可信。"""
    peaks = {}
    try:
        import sqlite3
        con = sqlite3.connect(f'file:{LEDGER}?mode=ro', uri=True, timeout=5)
        for code, pk in con.execute("SELECT code, peak_price FROM position_peaks").fetchall():
            if pk: peaks[str(code)] = max(peaks.get(str(code), 0), float(pk))
        for code, pk in con.execute(
                "SELECT code, peak_price FROM strategy_positions "
                "WHERE peak_price IS NOT NULL AND peak_price > 0").fetchall():
            peaks[str(code)] = max(peaks.get(str(code), 0), float(pk))
        con.close()
    except Exception:
        return {}
    return peaks


def evaluate(code, info, px, today, peaks=None, market_chg=None):
    """返回该票本轮意见列表 [(icon, text, key)]，key 用于当日去重"""
    opinions = []
    peaks = peaks or {}
    sc = info.get('signal_close')
    prev = info.get('prev_close') or sc
    name = info.get('name') or code
    lists = [l['account'] for l in info.get('in_lists', [])]
    chg_pct = (px / prev - 1) * 100 if prev else 0.0

    if lists and sc:
        vs_signal = (px / sc - 1) * 100
        star = '⭐' if len(lists) >= 2 else ''
        tag = f"[{'、'.join(lists)}]"
        if vs_signal > 5:
            opinions.append(('⚠️',
                f"{star}{code} {name} {tag} 现价{px}较信号日+{vs_signal:.1f}%，追高等回落",
                f'chase|{code}'))
        elif vs_signal < -3:
            opinions.append(('⛔',
                f"{code} {name} {tag} 现价{px}较信号日{vs_signal:.1f}%（跌超3%，执行端会缓/停买）",
                f'stopbuy|{code}'))
        elif vs_signal <= 2:
            opinions.append(('🟢',
                f"{star}{code} {name} {tag} 现价{px}（信号日{vs_signal:+.1f}%，日内{chg_pct:+.1f}%）建议买入区",
                f'buyzone|{code}'))
    for h in info.get('holds', []):
        acct = h['account']
        sl, tg = h.get('stop_loss'), h.get('target')
        cost = h.get('avg_cost') or 0
        pnl = (px / cost - 1) * 100 if cost else 0
        # R4 执行口径（2026-09-15 对齐）：止损永不比成本-6%更紧
        eff_sl = min(sl, cost * FLOAT_STOP_FLOOR) if (sl and cost) else sl
        if eff_sl and px <= eff_sl:
            opinions.append(('🔴',
                f"{code} {name}【{acct}】现价{px} 破执行止损{eff_sl} 盈亏{pnl:+.1f}% 建议卖出",
                f'sl|{acct}|{code}'))
        elif eff_sl and px <= eff_sl * 1.01:
            opinions.append(('🟠',
                f"{code} {name}【{acct}】现价{px} 距执行止损{eff_sl}仅{(px/eff_sl-1)*100:.1f}% 关注",
                f'nsl|{acct}|{code}'))
        if tg and px >= tg:
            opinions.append(('🎯',
                f"{code} {name}【{acct}】现价{px} 达目标{tg} 盈亏{pnl:+.1f}% 考虑止盈",
                f'tgt|{acct}|{code}'))
        # R3 回撤止盈引信（2026-09-15 补漏报）：价格2条件满足即提示，大盘开关单独点明
        pk = peaks.get(code) or 0
        if cost and pk >= cost * DRAWDOWN_MIN_GAIN and px <= pk * DRAWDOWN_RATIO:
            dd = (px / pk - 1) * 100
            if market_chg is not None and market_chg <= DRAWDOWN_MARKET_THRESHOLD:
                opinions.append(('🔴',
                    f"{code} {name}【{acct}】回撤止盈已触发：峰值{pk:.2f}回撤{dd:.1f}%+大盘{market_chg:+.1f}%≤-2%，执行端将卖出",
                    f'dd_fire|{acct}|{code}'))
            else:
                mkt_txt = f"大盘{market_chg:+.1f}%" if market_chg is not None else "大盘价未获取"
                opinions.append(('🟡',
                    f"{code} {name}【{acct}】回撤止盈引信：峰值{pk:.2f}已回撤{dd:.1f}%（{mkt_txt}，跌到-2%即触发批量卖出）盈亏{pnl:+.1f}%",
                    f'ddfuse|{acct}|{code}'))
    return opinions


def main():
    uni = load_json(UNIVERSE, None)
    if not uni:
        print('❌ 无 opinion_universe.json（夜间简报未生成？）')
        return
    today = datetime.now().strftime('%Y%m%d')
    if str(uni.get('signal_date', '')) >= today and not DRY:
        # 池子还是昨天的（今天夜间简报没跑），照常监控但提示一次
        pass

    now = datetime.now()
    from core.trading_time import in_trading_session
    if not in_trading_session(now) and not DRY:
        return  # 非交易时段静默
    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：休市日不烧 token 出意见
    from core.trade_calendar import is_trading_day
    if not is_trading_day() and not DRY:
        print('🚫 非交易日（tushare trade_cal 权威），跳过盘中意见')
        return

    state = load_json(STATE, {'date': today, 'pushed': []})
    if state.get('date') != today:
        state = {'date': today, 'pushed': []}
    # v2: seen = {key: {'n': 已推次数, 'px': 上次推送价}}；兼容旧 pushed 列表
    seen = state.get('seen') or {k: {'n': 1, 'px': None} for k in state.get('pushed', [])}
    state['seen'] = seen

    codes = list(uni['universe'])
    prices = fetch_prices_batch(codes)
    if not prices:
        print('⚠️ Sina 无行情（非交易日/停牌日），本轮跳过')
        return
    # 执行端口径输入（2026-09-15）：持仓峰值 + 当日大盘涨跌幅（同 intraday_decision.get_market_status）
    peaks = load_peaks()
    market_chg = None
    try:
        from core.prices import fetch_price_live
        _px0, _chg = fetch_price_live('000001')
        if _px0 and _px0 > 0:
            market_chg = _chg
    except Exception:
        pass

    def allow_resend(key, px):
        """方案一：当日同票同类型最多2条；第2条须较上次推送价偏离≥1.5%（意见过期重发）"""
        rec = seen.get(key)
        if rec is None:
            return True
        if rec['n'] >= 2:
            return False
        last_px = rec.get('px')
        if last_px and px and abs(px / last_px - 1) * 100 >= 1.5:
            return True
        return False

    new_ops = []   # (icon, text, key, code)
    all_ops = []   # 全部当前触发（尾盘总结用，含已推过的）
    for code, info in uni['universe'].items():
        px = prices.get(code)
        if not px:
            continue
        for icon, text, key in evaluate(code, info, px, today, peaks, market_chg):
            all_ops.append((icon, text, key, code))
            if not allow_resend(key, px):
                continue
            if seen.get(key, {}).get('n', 0) >= 1:
                last = seen[key].get('px')
                text = text + f"（重发：前次价{last}→现价{px}）"
            new_ops.append((icon, text, key, code))

    # 排序: 卖/止损意见优先，其次买入
    order = {'🔴': 0, '🎯': 1, '🟠': 2, '🟡': 3, '⛔': 4, '🟢': 5, '⚠️': 6}
    new_ops.sort(key=lambda x: (order.get(x[0], 9), x[3]))

    # 方案二：尾盘总结（14:25-15:00 窗口内触发一次，无视去重）
    # state['closing_done'] = 当日已总结标记；--closing 强制
    is_closing = (now.hour == 14 and now.minute >= 25) or now.hour == 15
    do_closing = '--closing' in sys.argv or (
        is_closing and state.get('closing_done') != today and not DRY)

    if not new_ops and not do_closing:
        return  # 无新意见 → 完全静默（watchdog 模式）

    ts = now.isoformat(timespec='seconds')

    def write_log(items):
        with LOG.open('a', encoding='utf-8') as f:
            for icon, text, key, code in items:
                f.write(json.dumps({'ts': ts, 'icon': icon, 'text': text, 'key': key,
                                    'code': code, 'price': prices.get(code)},
                                   ensure_ascii=False) + '\n')

    def push(msg):
        with open(PUSH_LOCK, 'a') as lockf:
            try:
                fcntl.flock(lockf, fcntl.LOCK_EX)
            except Exception:
                pass
            try:
                r = subprocess.run(['hermes', 'send', '-t', QQ_TARGET, msg],
                                   capture_output=True, timeout=30)
                return r.returncode == 0
            except Exception as e:
                print(f'push err: {e}')
                return False

    # —— 常规新意见 ——
    if new_ops:
        header = f"【盘中意见 {now.strftime('%H:%M')}】信号日{uni.get('signal_date')} 现价快照"
        body = '\n'.join(f"{icon} {text}" for icon, text, _, _ in new_ops)
        msg = f"{header}\n{body}"
        if len(msg) > 3800:
            msg = msg[:3800] + '\n…（余下见面板）'
        write_log(new_ops)  # 留档 jsonl（无论推没推送都记）
        if DRY:
            print(msg)
            print(f'[dry] 新意见{len(new_ops)}条，未推送未记state')
        else:
            ok = push(msg)
            if ok:
                for _, _, k, _c in new_ops:
                    rec = seen.setdefault(k, {'n': 0, 'px': None})
                    rec['n'] = rec['n'] + 1
                    rec['px'] = prices.get(_c)
                state['pushed'] = sorted(seen)
                STATE.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            print(f"{'✅' if ok else '❌'} 推送{'成功' if ok else '失败'}: {len(new_ops)}条新意见")

    # —— 尾盘总结（无视去重，当前仍触发的全部重推一条快照）——
    if do_closing and all_ops:
        all_ops.sort(key=lambda x: (order.get(x[0], 9), x[3]))
        header = f"【尾盘总结 {now.strftime('%H:%M')}】信号日{uni.get('signal_date')} 当前仍在触发区的票"
        body = '\n'.join(f"{icon} {text}" for icon, text, _, _ in all_ops)
        msg = f"{header}\n{body}"
        if len(msg) > 3800:
            msg = msg[:3800] + '\n…（余下见面板）'
        closing_items = [(i, t + '（尾盘总结）', k + '|closing', c)
                         for i, t, k, c in all_ops]
        write_log(closing_items)
        if DRY:
            print(msg)
            print(f'[dry] 尾盘总结{len(all_ops)}条')
        else:
            ok2 = push(msg)
            if ok2:
                state['closing_done'] = today
                state['pushed'] = sorted(seen)
                STATE.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
            print(f"{'✅' if ok2 else '❌'} 尾盘总结推送{'成功' if ok2 else '失败'}: {len(all_ops)}条")


if __name__ == '__main__':
    main()