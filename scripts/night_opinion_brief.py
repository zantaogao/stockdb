#!/usr/bin/env python3
"""盘中意见层 — 夜间简报生成器（2026-08-30 上线）。

每晚（补拉链之后）跑一次：
  1. 读各策略账户的最新 Top10 名单（信号日 = 最近一个 ≤ 今天的日期；账户清单
     import 自 strategy_accounts_daily.ACCOUNTS，唯一来源，2026-09-16 起）
  2. 读主账户持仓(ledger.holdings) + 各策略账户持仓(strategy_positions)
  3. 用 tushare 日线算：昨收、近5日涨幅、MA20、BOLL中轨、20日高、昨信号价(入场参考)
     ——均线类指标用前复权价（2026-09-16 修复，除权票不失真）
  4. 按重评日历判定明日是否各账户"调仓日"（重评日整仓重建 = 密集买卖预警）
  5. 产出:
       analysis/YYYYMMDD_brief.md   — 给主 agent 的意见底稿
       analysis/opinion_universe.json — 盘中脚本 intraday_opinion.py 的关注池(名单+持仓)

只做只读分析，不写 pending.json、不下单。
"""
import sqlite3
import duckdb
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LEDGER = BASE / 'ledger.db'
SIGNALS = BASE / 'signals.db'
TUSHARE = BASE / 'tushare.db'
ANALYSIS_DIR = BASE / 'analysis'

# 策略账户清单：直接 import strategy_accounts_daily 的 ACCOUNTS（唯一来源）。
# 2026-09-16 修复：原来这里手抄了 5 账户旧拷贝（CMMR 两户已 09-11 销户、缺 agent_auto/
# reg10_solo、rebalance 窗口还是 10/15），导致盘中意见池漏掉新账户、"距调仓还剩几天"算错。
# closed=True（09-11 销户冻结）不进意见池；manual=True（agent_auto）只进持仓不进名单。
# 回滚：scripts/night_opinion_brief.py.bak.20260916
from strategy_accounts_daily import ACCOUNTS as _SAD_ACCOUNTS
REBALANCE_DEFAULT = 10
ACCOUNTS = {aid: dict(cfg) for aid, cfg in _SAD_ACCOUNTS.items() if not cfg.get('closed')}


def rank_pct(vals):
    """横截面百分位 rank（同 strategy_accounts_daily 口径）"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    n = len(vals)
    for r, i in enumerate(order):
        ranks[i] = (r + 1) / n * 100
    return ranks


def get_top10(sig, d, src):
    """信号日 d 的目标 top10（照抄 strategy_accounts_daily.get_signal_targets 逻辑，不滤价格）"""
    if src == 'fusion_3f':
        rows = sig.execute("""
            SELECT stock_code, fusion_3f_score FROM fusion_3f_signals
            WHERE REPLACE(date,'-','')=? AND signal='强买'
            ORDER BY fusion_3f_score DESC, flow_alpha DESC LIMIT 10""", (d,)).fetchall()
        return [(r[0], float(r[1])) for r in rows]
    if src == 'cmmr':
        rows = sig.execute("""
            SELECT stock_code, cmmr_score FROM signal_history
            WHERE REPLACE(date,'-','')=? AND cmmr_score > 0
            ORDER BY cmmr_score DESC LIMIT 10""", (d,)).fetchall()
        return [(r[0], float(r[1])) for r in rows]
    if src == 'cmmr_fusion':
        rows = sig.execute("""
            SELECT stock_code, fusion_score_cmmr FROM signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score_cmmr IS NOT NULL AND fusion_score_cmmr > 0""",
                           (d,)).fetchall()
        scores = sorted(float(r[1]) for r in rows)
        p85 = scores[int(len(scores) * 0.85)] if scores else 0
        picks = sorted([(r[0], float(r[1])) for r in rows if float(r[1]) >= p85],
                       key=lambda x: x[1], reverse=True)
        return picks[:10]
    if src == 'fusion_center':
        rows = sig.execute("""
            SELECT stock_code, score FROM fusion_center_signals
            WHERE REPLACE(date,'-','')=? AND signal='强买'
            ORDER BY score DESC LIMIT 10""", (d,)).fetchall()
        return [(r[0], float(r[1])) for r in rows]
    if src in ('center_dual', 'agent_auto'):
        # 中枢 score + 三模型 fusion_score 双信号百分位等权（同主脚本算法；2026-09-16 补 agent_auto 同款口径）
        ct = sig.execute("""
            SELECT stock_code, score FROM fusion_center_signals
            WHERE REPLACE(date,'-','')=? AND signal='强买'""", (d,)).fetchall()
        md = sig.execute("""
            SELECT stock_code, fusion_score FROM signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL""", (d,)).fetchall()
        ctmap = {r[0]: float(r[1]) for r in ct}
        # 三模型取当日 top50 与中枢并集打分
        md_top = sig.execute("""
            SELECT stock_code, fusion_score FROM signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
            ORDER BY fusion_score DESC LIMIT 50""", (d,)).fetchall()
        mdmap = {r[0]: float(r[1]) for r in md_top}
        common = sorted(set(ctmap) | set(mdmap))
        if not common:
            return []
        a = [ctmap.get(c, min(ctmap.values()) if ctmap else 0) for c in common]
        b = [mdmap.get(c, min(mdmap.values()) if mdmap else 0) for c in common]
        ra, rb = rank_pct(a), rank_pct(b)
        comb = {c: 0.5 * ra[i] + 0.5 * rb[i] for i, c in enumerate(common)}
        picks = sorted(comb.items(), key=lambda x: x[1], reverse=True)
        return picks[:10]
    if src == 'reg10':
        # 2026-09-16 补（10d独立账户）：reg10 纯排序 top10，同 strategy_accounts_daily 口径
        rows = sig.execute("""
            SELECT stock_code, reg10 FROM signal_history
            WHERE REPLACE(date,'-','')=? AND reg10 IS NOT NULL
            ORDER BY reg10 DESC, stock_code LIMIT 10""", (d,)).fetchall()
        return [(r[0], float(r[1])) for r in rows]
    return []


def main():
    today = datetime.now().strftime('%Y%m%d')
    ledger = sqlite3.connect(str(LEDGER), timeout=30)
    sig = sqlite3.connect(str(SIGNALS), timeout=30)
    ts = duckdb.connect(str(TUSHARE), read_only=True)

    # 信号日 = 最近一个 ≤ 今天的信号日（2026-09-16 修复：原 `< 今天` 在夜里跑时把当晚
    # 22:11 已写入库的今日信号排除掉，池子永远落后一天；白天跑时今日尚无信号，取到的
    # 仍是昨日，语义不变。回滚 scripts/night_opinion_brief.py.bak.20260916）
    d = sig.execute(
        "SELECT MAX(REPLACE(date,'-','')) FROM fusion_3f_signals WHERE REPLACE(date,'-','') <= ?",
        (today,)).fetchone()[0]
    if not d:
        print('无信号日，退出')
        return
    print(f'信号日 {d}（明日盘中执行名单）')

    # ---- 名称表 + 日线指标 ----
    name_map = {}
    try:
        for code, name in ts.execute("SELECT ts_code, name FROM stock_basic").fetchall():
            name_map[str(code).split('.')[0]] = name
    except Exception:
        pass
    for r in sig.execute("SELECT DISTINCT stock_code, stock_name FROM signal_history WHERE stock_name IS NOT NULL").fetchall():
        name_map.setdefault(r[0], r[1])

    # 各账户 top10 + 持仓
    lists = {}      # aid -> [(code, score)]
    holds = {}      # aid -> [ {code,name,shares,avg_cost,stop_loss,target} ]
    for aid, cfg in ACCOUNTS.items():
        lists[aid] = get_top10(sig, d, cfg['src'])
    ledger.row_factory = sqlite3.Row
    for aid in ACCOUNTS:
        holds[aid] = [dict(r) for r in ledger.execute(
            "SELECT code,name,shares,avg_cost,buy_date,stop_loss,target FROM strategy_positions WHERE account_id=?",
            (aid,)).fetchall()]
        for h in holds[aid]:
            h['buy_date'] = str(h['buy_date']).replace('-', '')

    main_holds = [dict(r) for r in ledger.execute(
        "SELECT code,name,shares,avg_cost,buy_date,target_price,stop_loss FROM holdings WHERE status='hold'").fetchall()]
    for h in main_holds:
        h['buy_date'] = str(h['buy_date']).replace('-', '')

    # 调仓日判定：strategy_positions 最后成交价日 + rebalance 个交易日数
    next_trade_days = [r[0] for r in ts.execute(
        "SELECT DISTINCT trade_date FROM daily WHERE trade_date > ? ORDER BY trade_date LIMIT 25",
        (d,)).fetchall()]
    from datetime import timedelta
    # 明日日线未入库时回退：夜间跑(>=20点)取下一个非周末日；白天/凌晨跑且今天是工作日且晚于信号日→今天就是执行日
    if next_trade_days:
        exec_date = next_trade_days[0]
    else:
        _now = datetime.now()
        if _now.hour >= 20 or today <= d:
            _c = _now + timedelta(days=1)
        else:
            _c = _now
        while _c.weekday() >= 5:
            _c += timedelta(days=1)
        exec_date = _c.strftime('%Y%m%d')
    rebalance_info = {}
    # 距上次调仓已过几个交易日 = (last_re, 信号日d] 的库内交易日 + 执行日1天
    all_days = [r[0] for r in ts.execute(
        "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date").fetchall()]
    for aid, cfg in ACCOUNTS.items():
        need = cfg.get('rebalance', REBALANCE_DEFAULT)
        last_re = ''
        try:
            row = ledger.execute(
                "SELECT config_json FROM strategy_accounts_meta WHERE account_id=?", (aid,)).fetchone()
            if row and row[0]:
                last_re = str(json.loads(row[0]).get('last_rebalance_date', '')).replace('-', '')
        except Exception:
            pass
        if last_re:
            # 已过交易日：库内 > last_re 且 <= 信号日d 的天数；再加执行日当天1个交易日
            n_past = len([x for x in all_days if last_re < x <= d])
            n_after = n_past + 1
        else:
            n_after = 999
        manual = bool(cfg.get('manual'))  # agent 自主择时账户无机械重评日历
        rebalance_info[aid] = {
            'last_rebalance': last_re,
            'need': need if not manual else None,
            'manual': manual,
            'due': (not manual) and n_after >= need,
            'days_left': 999 if manual else max(need - n_after, 0),
        }

    # ---- 关注池 = 5×top10 ∪ 全部策略持仓 ∪ 主账户持仓 ----
    universe = {}

    def add(code):
        code = str(code)
        if code not in universe:
            universe[code] = {
                'name': name_map.get(code, ''),
                'in_lists': [], 'holds': [],
            }

    for aid, cfg in ACCOUNTS.items():
        for code, score in lists[aid]:
            add(code)
            universe[code]['in_lists'].append({'account': cfg['name'], 'score': round(score, 4)})
    for aid in ACCOUNTS:
        for h in holds[aid]:
            add(h['code'])
            universe[h['code']]['holds'].append({'account': cfg_name(aid), 'shares': h['shares'],
                                                 'avg_cost': h['avg_cost'], 'stop_loss': h['stop_loss'],
                                                 'target': h['target']})
    for h in main_holds:
        add(h['code'])
        universe[h['code']]['holds'].append({'account': '主账户', 'shares': h['shares'],
                                             'avg_cost': h['avg_cost'], 'stop_loss': h['stop_loss'],
                                             'target': h['target_price']})

    # 日线指标（昨收/近5日涨幅/MA20/BOLL中轨/20日高/信号日收盘=入场参考价）
    # 2026-09-16 修复：MA20/BOLL/20日高/5日涨幅改用前复权价（close×adj_factor÷最新adj_factor，
    # 标定到最新一天=现价口径）。原实现用不复权价，除权票的均线方向都会算反
    # （实例：和顺科技 09-01 除权×1.39，池子写"低于MA20 14%"，真实是"高于MA20 1.3%"）。
    # prev_close/signal_close 同为前复权口径——信号日至今无除权时与原值逐位相同。
    codes = list(universe)
    ts_codes = [c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ') for c in codes]
    q = ','.join('?' * len(ts_codes))
    daily = {}
    for r in ts.execute(f"""
        SELECT d.ts_code, d.trade_date, d.close, a.adj_factor FROM daily d
        LEFT JOIN adj_factor a ON a.ts_code = d.ts_code AND a.trade_date = d.trade_date
        WHERE d.ts_code IN ({q}) AND d.trade_date >= ?
        ORDER BY d.ts_code, d.trade_date""", (*ts_codes, str(int(d) - 400))).fetchall():
        daily.setdefault(str(r[0])[:6], []).append((str(r[1]), float(r[2]), float(r[3]) if r[3] else None))
    for code, series in daily.items():
        series.sort()
        # 前复权标定：adj 缺失日沿用前值（adj_factor 只在除权日变化）
        last_adj = None
        rows_adj = []
        for dt, c, a in series:
            if a is None:
                a = last_adj
            else:
                last_adj = a
            rows_adj.append((dt, c, a))
        latest_adj = last_adj or 1.0
        closes = [round(c * (a / latest_adj), 4) for _, c, a in rows_adj]
        u = universe.get(code)
        if not u:
            continue
        u['prev_close'] = closes[-1]
        u['ma20'] = round(sum(closes[-20:]) / min(20, len(closes[-20:])), 3) if len(closes) >= 5 else None
        u['high20'] = round(max(closes[-20:]), 3) if len(closes) >= 5 else None
        u['chg5d'] = round((closes[-1] / closes[-6] - 1) * 100, 2) if len(closes) >= 6 else None
        sig_close = [c for dt, c, _a in rows_adj if dt == d]
        u['signal_close'] = sig_close[0] if sig_close else closes[-1]
        # BOLL 中轨 = ma20，带宽参考
        if u.get('ma20') and len(closes) >= 20:
            m = u['ma20']
            std = (sum((c - m) ** 2 for c in closes[-20:]) / 20) ** 0.5
            u['boll_up'] = round(m + 2 * std, 3)
            u['boll_low'] = round(m - 2 * std, 3)

    # ---- 写 opinion_universe.json（盘中脚本消费） ----
    ANALYSIS_DIR.mkdir(exist_ok=True)
    out = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'signal_date': d,
         'exec_date': exec_date,
        'accounts': {aid: {'name': cfg['name'], 'rebalance': rebalance_info[aid]}
                     for aid, cfg in ACCOUNTS.items()},
        'top10': {cfg['name']: [{'code': c, 'score': s, 'name': name_map.get(c, '')}
                                for c, s in lists[aid]] for aid, cfg in ACCOUNTS.items()},
        'main_holdings': main_holds,
        'strategy_holdings': {cfg_name(aid): holds[aid] for aid in ACCOUNTS},
        'universe': universe,
    }
    (ANALYSIS_DIR / 'opinion_universe.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

    # ---- 写 Markdown 简报（给主 agent 的意见底稿） ----
    md = []
    md.append(f'# 盘中意见简报 {d} → 执行日 {exec_date}')
    md.append('')
    reb = [cfg_name(a) for a in ACCOUNTS if rebalance_info[a]['due']]
    soon = [f"{cfg_name(a)}(还剩{rebalance_info[a]['days_left']}个交易日)"
            for a in ACCOUNTS if not rebalance_info[a]['due'] and rebalance_info[a]['days_left'] <= 2]
    md.append(f'## 调仓日历')
    md.append(f'- **明日调仓日: {"、".join(reb) if reb else "无"}**' +
              ('  ⚠️ 调仓日=整仓重建，密集买卖' if reb else ''))
    if soon:
        md.append(f'- 临近调仓: {"、".join(soon)}')
    md.append('')
    md.append(f'## 策略名单（明日买入候选）')
    for aid, cfg in ACCOUNTS.items():
        rb_txt = 'agent自主择时' if cfg.get('manual') else f"重评{cfg.get('rebalance', REBALANCE_DEFAULT)}日"
        md.append(f'### {cfg["name"]} ({rb_txt})')
        for c, s in lists[aid]:
            u = universe.get(str(c), {})
            extra = []
            if u.get('chg5d') is not None:
                extra.append(f'近5日{u["chg5d"]:+.1f}%')
            if u.get('signal_close'):
                extra.append(f'信号日收盘{u["signal_close"]}')
            md.append(f'- {c} {name_map.get(str(c), "")} 分{s:.2f}' +
                      (' (' + ', '.join(extra) + ')' if extra else ''))
        md.append('')
    md.append('## 当前持仓（卖出/止损观察）')
    md.append(f'### 主账户 {len(main_holds)}只')
    for h in main_holds:
        md.append(f'- {h["code"]} {h["name"]} 成本{h["avg_cost"]} 止损{h["stop_loss"]} 目标{h["target_price"]}')
    for aid in ACCOUNTS:
        md.append(f'### {cfg_name(aid)} {len(holds[aid])}只')
        for h in holds[aid]:
            md.append(f'- {h["code"]} {h["name"]} 成本{h["avg_cost"]} 止损{h["stop_loss"]} 目标{h["target"]}')
    md.append('')
    md.append(f'关注池共 {len(universe)} 只（策略名单去重 ∪ 全部持仓）')
    brief_path = ANALYSIS_DIR / f'{d}_brief.md'
    brief_path.write_text('\n'.join(md), encoding='utf-8')

    print(f'✅ 简报: {brief_path}')
    print(f'✅ 关注池: {ANALYSIS_DIR}/opinion_universe.json ({len(universe)}只)')
    print(f'调仓日: {reb if reb else "无"} | 临近: {soon if soon else "-"}')
    ledger.close(); sig.close(); ts.close()


def cfg_name(aid):
    return ACCOUNTS[aid]['name']


if __name__ == '__main__':
    main()