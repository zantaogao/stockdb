#!/usr/bin/env python3
"""每日自动对账（MacBook v2 版，2026-08-31 从 M2 版移植，修复原缺失导致的连续漏报）。
范围: trade_log 全量 + 主账户 holdings + 6个策略账户 sim_accounts JSON（v2: 主库 ledger.db）。
检查:
  1. trade_log 质量: 价格>0 / 数量>0 / BUY必须100整数倍 / trade_time缺失
  2. 重复检测: 同(code,direction,date,strategy)多条且时间戳不同
  3. 策略账户 JSON 重建核对: trades逐笔重建现金+持仓 vs JSON现状（初始100万）
  4. JSON trades vs trade_log 全量逐笔匹配（方向/日期/数量/价格）
  5. 主账户强检查: 每只股最后交易方向 vs holdings（BUY后应在仓/SELL后应不在仓）
  6. 双向持仓-流水核对（2026-08-31 新增，P0 根因）: 方向二=positions 每行必须有配对 BUY
     （幽灵持仓：写 positions 没写 trades，8/28 七行案例）；方向一=累计买入>卖出
     但 positions 无该票（丢行，300109 案例）；主账户 holdings 每行必须全库有 BUY（688636 案例）
口径注意: 主账户 amount=净额（含佣金±0.03%）、策略账户 amount=总额（无佣金）——重建一律用
price×shares，不碰 amount，避免两套口径混用造成回放漂移。
只读审计，不改任何数据。输出约定: 正常 → stdout 为空; 有问题 → 每行一条 [对账] 告警。
"""
import sqlite3, json, os, sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
STATE_DB = BASE / 'ledger.db'   # v2 主库
SIM_DIR = BASE / 'sim_accounts'
STRATS = []
# 策略账户动态发现（2026-09-04：原静态列表漏 agent_auto → agent 全权账户不在对账范围；
# 改用 sim_accounts 实际文件同步，自动覆盖新账户）
for _f in sorted(os.listdir(str(SIM_DIR))):
    if not _f.endswith('.json') or _f == 'main.json':
        continue
    try:
        _d = json.load(open(SIM_DIR / _f))
    except Exception:
        continue
    if isinstance(_d.get('positions'), list) and 'cash' in _d:
        STRATS.append(_f[:-5])
INIT = 1000000.0
# 已知遗留缺口（2026-08-24 审计确认）: 8/4~8/14 期间卖出、SELL 记录随主账户 bug 全丢、
# 无证据反推价格，不编造补录。账实(现金/持仓)本就正确，仅缺流水。
KNOWN_MISSING_SELL = {'300259', '300668', '603538', '688168', '688677'}
# 已知缺 BUY 流水（2026-08-31 审计确认）: 688636 智明达 7/30、688175 主账户早期建仓，
# 持仓真实存在、成本有据，仅缺 BUY 流水，不编造补录，登记跳过。
# 另: 主账户"有卖无买"现金偏差 600508/600963/688386/688691 为 8/4 前流水残缺同源问题，
# 当日收益用总资产口径不受影响，历史现金序列不可信（已登记，不追补）。
KNOWN_MISSING_BUY = {'688636', '688175'}

c = sqlite3.connect(str(STATE_DB))
issues = []

# ── 0. 权威源护栏（2026-09-17 新增）──
# 策略账户权威源 = ledger.db（strategy_accounts_meta + strategy_positions + trade_log），
#   sim_accounts/<aid>.json 只是 AccountStore.save() 导出的派生显示层（面板持仓页读它）；
# 主账户权威源 = ledger.db 的 holdings/account_balance（exec_agent._load_main_from_db），
#   sim_accounts/main.json 是 2026-08-03 停用后的退役件（mtime 停在 8/3 14:12，至今无人写）。
# 2026-09-16 事故：手动碎仓脚本绕过 AccountStore.save 直写 DB → fusion3f(5笔)/fusion_dual(12笔)
#   的 JSON 滞后，面板这两个账户多显示 17 只已卖票、现金少记 32,590 元（账本自洽、无资损）。
# 规矩：手动改账必须走 AccountStore.save（派生 JSON 自动导出）；只写了 DB 就补跑
#   python3 -B scripts/sync_derived_json.py。
# main.json 一旦重新出现 = 有代码又把它当账本写 → 必须人工确认，故直接告警。
if (SIM_DIR / 'main.json').exists():
    issues.append("[对账][护栏] sim_accounts/main.json 重新出现（该文件 2026-08-03 起已停用，主账户唯一源是 ledger.db）"
                  " → 禁止用该 JSON 覆盖或对齐 holdings/account_balance；策略账户改账请走 AccountStore.save"
                  "（派生 JSON 自动导出）或改完跑 scripts/sync_derived_json.py")

# ── 0b. trade_date 格式护栏（2026-09-17 新增，与 M2 同款）──
# daily_report.py 用 trade_date='YYYY-MM-DD'(ISO) 查"当日"流水；裸码(YYYYMMDD)行会被**漏读**
# → 昨日持仓/现金反推少算该笔成交 → 当日收益偏差（M2 实测：一笔 600 股卖出因裸码，
# 报告当日收益 +0.59% 被算成 +0.56%，与面板打架）。本机 2026-09-17 已把历史 60 行裸码归一化。
for _b in c.execute("SELECT id, code, direction, REPLACE(trade_date,'-',''), trade_date FROM trade_log "
                    "WHERE trade_date NOT LIKE '%-%'").fetchall():
    issues.append(f"[对账][格式] trade_log id={_b[0]} {_b[1]} {_b[2]} 日期裸码({_b[4]})"
                  f" → daily_report 按 ISO 查当日流水会漏读该笔，请改成 YYYY-MM-DD")

# ── 1. trade_log 质量 ──
rows = c.execute("""
    SELECT id, code, name, direction, price, quantity, amount, trade_date, trade_time, strategy
    FROM trade_log ORDER BY REPLACE(trade_date,'-',''), trade_time, id
""").fetchall()
for r in rows:
    rid, code, name, direction, price, quantity, amount, tdate, ttime, strat = r
    d = str(tdate).replace('-', '')
    if not price or price <= 0:
        issues.append(f"[对账][质量] {d} {strat or 'main'} {code} {direction} price={price}")
    if not quantity or quantity <= 0:
        issues.append(f"[对账][质量] {d} {strat or 'main'} {code} {direction} quantity={quantity}")
    if direction == 'BUY' and quantity and quantity % 100 != 0:
        issues.append(f"[对账][质量] {d} {strat or 'main'} {code} BUY 数量{quantity} 非100整数倍")
    if not amount or amount <= 0:
        issues.append(f"[对账][质量] {d} {strat or 'main'} {code} {direction} amount={amount} 异常")
    if not ttime and d >= '20260804':
        issues.append(f"[对账][质量] {d} {strat or 'main'} {code} {direction} trade_time缺失")
    # 0928 新增: quantity×price 与 amount 交叉校验（M2 同款 bug 防线——exec_agent
    # 现金截量后 result['shares'] 未回写，流水印计划量/金额印实际量。主账户佣金
    # ±0.03%、策略账户无佣金，1% 容差覆盖费率不误报；301575 案偏差 3% 必抓）
    if price and quantity and amount:
        _dev = abs(quantity * price - amount) / amount
        if _dev > 0.01:
            issues.append(f"[对账][量金不符] {d} {strat or 'main'} {code} {direction} "
                          f"quantity={quantity}×{price}={quantity*price:.0f} vs amount={amount:.0f} "
                          f"(偏差{_dev*100:.1f}%,疑现金截量未回写)")

# ── 2. 重复: 同(code,direction,date,strategy)多条且时间戳不同 ──
# 2026-09-11 修订：策略账户同日多次 BUY 不报——topup='gap' 口径下窗口内每轮运行
# 都会把新回笼现金补进已持有目标仓（9/11 603036 两笔 = 09:35 补缺 + 10:05 止损回笼后再补，
# 均为脚本本意）。真写重由检查③④（JSON 逐笔重建 vs 流水）兜底，此启发式只防 SELL/主账户。
dup = defaultdict(list)
for r in rows:
    rid, code, name, direction, price, quantity, amount, tdate, ttime, strat = r
    if direction == 'BUY' and strat and strat != 'main':
        continue  # 策略账户 BUY 豁免（gap 补仓天然同日多笔）
    key = (code, direction, str(tdate).replace('-', ''), strat or 'main')
    dup[key].append((rid, price, quantity, ttime))
for key, items in dup.items():
    if len(items) > 1:
        times = set(i[3] for i in items)
        if len(times) > 1:
            issues.append(f"[对账][重复] {key[2]} {key[0]} {key[1]} {key[3]} {len(items)}条")

# ── 3. 策略账户 JSON 重建核对（全量，初始100万逐笔） ──
for aid in STRATS:
    p = SIM_DIR / f'{aid}.json'
    if not p.exists():
        issues.append(f"[对账][JSON] {aid}.json 不存在")
        continue
    d = json.load(open(p))
    # 按 (date, trade_time) 排序后重放：补录行会插到数组头部（08-31 backfill 如此），
    # 不按时间排序会把后买的票当成"卖出超持仓"误报（09-03 300109 案例）
    trades = d.get('trades', [])
    # 2026-09-04 除权事件并入重放：送转/派息不进 trades（交易流水纯净），
    # 证据在 ca_adjustments（账户粒度，主库 ledger.db）→ 同日期 ca 排最前（盘前调整）
    evs = []
    for code, exd, sh_add, net in c.execute(
            "SELECT code, ex_date, shares_add, net_div FROM ca_adjustments WHERE account=? ORDER BY ex_date",
            (aid,)).fetchall():
        evs.append((str(exd).replace('-', ''), '', 0, ('ca', code, int(sh_add or 0), float(net or 0))))
    for t in trades:
        evs.append((str(t.get('date', '')).replace('-', ''), str(t.get('trade_time', '')), 1, ('t', t)))
    evs.sort(key=lambda x: (x[0], x[1], x[2]))
    # 2026-09-04：现金起点用账户自身 initial_capital（新账户兼容；缺省 100 万不变）
    cash = d.get('initial_capital', INIT)
    held = {}
    for _dn, _tt, _pri, payload in evs:
        if payload[0] == 'ca':
            _, code, sh_add, net = payload
            held[code] = held.get(code, 0) + sh_add  # 送转增股（非交易）
            cash += net                            # 股息净额（非交易）
            continue
        t = payload[1]
        code = t.get('code'); action = t.get('action'); shares = t.get('shares', 0); price = t.get('price', 0)
        if action == '买入':
            cash -= shares * price
            held[code] = held.get(code, 0) + shares
        elif action == '卖出':
            cash += shares * price
            if held.get(code, 0) < shares:
                issues.append(f"[对账][重建] {aid} 卖出超持仓: {code} 卖{shares} 持有{held.get(code,0)} @{t.get('date')}")
            held[code] = held.get(code, 0) - shares
    json_cash = d.get('cash', 0)
    json_held = {x['code']: x.get('shares', 0) for x in d.get('positions', [])}
    if abs(cash - json_cash) > 1:
        issues.append(f"[对账][重建] {aid} 现金不符: 重建{cash:.0f} vs JSON{json_cash:.0f}（差{cash-json_cash:.0f}）")
    all_codes = set(held) | set(json_held)
    for code in all_codes:
        if held.get(code, 0) != json_held.get(code, 0):
            issues.append(f"[对账][重建] {aid} {code} 持仓不符: 重建{held.get(code,0)} vs JSON{json_held.get(code,0)}")

# ── 4. JSON trades vs trade_log 全量逐笔匹配 ──
for aid in STRATS:
    p = SIM_DIR / f'{aid}.json'
    if not p.exists():
        continue
    d = json.load(open(p))
    jtrades = d.get('trades', [])
    tl = c.execute("""
        SELECT code, direction, price, quantity, REPLACE(trade_date,'-','')
        FROM trade_log WHERE strategy=? ORDER BY REPLACE(trade_date,'-',''), trade_time, id
    """, (aid,)).fetchall()
    jset = defaultdict(int)
    for t in jtrades:
        act = 'BUY' if t.get('action') == '买入' else 'SELL'
        key = (t.get('code'), str(t.get('date', '')).replace('-', ''), act, t.get('shares'), round(t.get('price', 0), 2))
        jset[key] += 1
    tset = defaultdict(int)
    for code, direction, price, quantity, tdate in tl:
        key = (code, tdate, direction, quantity, round(price, 2))
        tset[key] += 1
    only_j = set(jset) - set(tset)
    only_t = set(tset) - set(jset)
    if only_j:
        issues.append(f"[对账][流水] {aid}: JSON有而trade_log无 {len(only_j)}笔: {[(k[0],k[1],k[2],k[3]) for k in list(only_j)[:5]]}")
    if only_t:
        issues.append(f"[对账][流水] {aid}: trade_log有而JSON无 {len(only_t)}笔: {[(k[0],k[1],k[2],k[3]) for k in list(only_t)[:5]]}")

# ── 5. 主账户强检查: 最后交易方向 vs holdings ──
holdings = c.execute("SELECT code, shares FROM holdings").fetchall()
hold_codes = {h[0] for h in holdings}
main_trades = c.execute("""
    SELECT code, direction FROM trade_log
    WHERE (strategy IS NULL OR strategy='main')
    ORDER BY code, REPLACE(trade_date,'-',''), trade_time, id
""").fetchall()
last_dir = {}
for code, direction in main_trades:
    last_dir[code] = direction
for code in sorted(set(last_dir) | hold_codes):
    if code in KNOWN_MISSING_SELL:
        continue
    if code in last_dir and last_dir[code] == 'BUY' and code not in hold_codes:
        issues.append(f"[对账][主账户] {code} 最后交易是BUY但不在持仓 → 卖出记录可能丢失")
    if code in last_dir and last_dir[code] == 'SELL' and code in hold_codes:
        issues.append(f"[对账][主账户] {code} 最后交易是SELL但仍在持仓 → 持仓未更新（部分卖出属正常，需人工看）")

# ── 6. 双向持仓-流水核对（2026-08-31 新增，P0 根因）──
for aid in STRATS:
    p = SIM_DIR / f'{aid}.json'
    if not p.exists():
        continue
    d = json.load(open(p))
    trades = d.get('trades', [])
    positions = d.get('positions', [])
    # 累计买卖量（JSON trades 为准）+ 除权送转增股（ca_adjustments，2026-09-04）
    buy_qty = defaultdict(int)
    sell_qty = defaultdict(int)
    ca_qty = defaultdict(int)
    for code, exd, sh_add, net in c.execute(
            "SELECT code, ex_date, shares_add, net_div FROM ca_adjustments WHERE account=?", (aid,)).fetchall():
        ca_qty[code] += int(sh_add or 0)
    for t in trades:
        code = t.get('code'); shares = t.get('shares', 0)
        if t.get('action') == '买入':
            buy_qty[code] += shares
        elif t.get('action') == '卖出':
            sell_qty[code] += shares
    pos_by_code = {}
    for x in positions:
        code = x.get('code')
        if not code:
            continue
        pos_by_code[code] = pos_by_code.get(code, 0) + x.get('shares', 0)
        if code not in buy_qty or buy_qty[code] <= 0:
            issues.append(f"[对账][幽灵持仓] {aid} {code} 持仓{x.get('shares')}股 但 trades 无任何买入记录 (buy_date={x.get('buy_date')})")
        elif buy_qty[code] + ca_qty.get(code, 0) < x.get('shares', 0):
            issues.append(f"[对账][幽灵持仓] {aid} {code} 持仓{x.get('shares')}股 > 累计买入{buy_qty[code]}+送转{ca_qty.get(code,0)}股")
    for code in set(buy_qty):
        net = buy_qty[code] - sell_qty.get(code, 0)
        if net > 0 and pos_by_code.get(code, 0) <= 0:
            issues.append(f"[对账][丢行] {aid} {code} 累计净买{net}股但持仓无该票 → 持仓行可能丢失")
main_buy_codes = {r[0] for r in c.execute(
    "SELECT DISTINCT code FROM trade_log WHERE direction='BUY' AND (strategy IS NULL OR strategy='main')").fetchall()}
for code, shares in holdings:
    if code in KNOWN_MISSING_BUY:
        continue
    if code not in main_buy_codes:
        issues.append(f"[对账][幽灵持仓] 主账户 {code} 持仓{shares}股 但全库无任何 BUY 流水")



# ── 7. 面板显示自检（2026-09-17 新增）──
# 账本对 ≠ 用户看到的数字对。本机架构：策略账户权威源 = ledger.db（meta/strategy_positions），
# sim_accounts/*.json 是派生物、面板持仓页读它；面板卡片的 nav/现金 读 strategy_accounts 最后一行。
# 这里独立复算（权威持仓×收盘价 + 现金）与 /api/dashboard 比对（面板不可达→静默跳过，由 system_guard 管）。
# 冻结/销户账户（NAV 表最后估值日 ≠ 本交易日）跳过：面板显示的**就是最后估值日的清算值**
# （2026-09-17 已给 fusion3f/fusion_dual 补 20260916 清算行 → 卡片 nav/现金/持仓数与持仓列表一致），
# 与新行的差异只是「日期非本交易日」，不再是残留不一致。
def _panel_sanity(issues_list):
    import json as _j
    import urllib.request as _u
    try:
        _d = _j.loads(_u.urlopen('http://localhost:8081/api/dashboard', timeout=10).read().decode())
    except Exception:
        return
    try:
        acc = (_d.get('accounts') or {})
        m = acc.get('main') or {}
        import duckdb as _duck
        holds = c.execute("SELECT code, shares FROM holdings WHERE status='hold'").fetchall()
        cash_db, init_db = c.execute(
            "SELECT cash_balance, initial_capital FROM account_balance WHERE account_id='main'").fetchone()
        close_map = {}

        def _load_closes(codes):
            _miss = [x for x in codes if x not in close_map]
            if not _miss:
                return
            _q = ','.join("'%s'" % (x + ('.SH' if x[0] in '69' else '.SZ')) for x in _miss)
            con = _duck.connect(str(BASE / 'tushare.db'), read_only=True,
                                config={'memory_limit': '512MB', 'threads': '2'})
            try:
                _last = con.execute(f"SELECT MAX(trade_date) FROM daily WHERE ts_code IN ({_q})").fetchone()[0]
                for _ts, _cl in con.execute(
                        f"SELECT ts_code, close FROM daily WHERE trade_date='{_last}' AND ts_code IN ({_q})").fetchall():
                    close_map[_ts[:6]] = float(_cl)
                return _last
            finally:
                con.close()

        _last_td = _load_closes([r[0] for r in holds]) if holds else None
        if m:
            mv = sum(sh * close_map.get(cd, 0) for cd, sh in holds)
            nav = (cash_db or 0) + mv
            for _k, _panel, _calc in (('现金', m.get('cash'), cash_db),
                                      ('持仓市值', m.get('position_value'), mv),
                                      ('总资产', m.get('total_nav'), nav)):
                if _panel is None or _calc is None:
                    continue
                if abs(_panel - _calc) > 1.0:
                    issues_list.append(f"[对账][面板] 主账户{_k}不符: 面板{_panel:,.2f} vs 复算{_calc:,.2f}"
                                       f"（差{_panel - _calc:+,.2f}）")
            if m.get('daily_ret') == 0 and m.get('daily_ret_pct') == 0 and abs(nav - (init_db or 1e6)) > 1:
                issues_list.append("[对账][面板] 主账户当日收益显示 0（资产非初始值）→ 疑似面板降级"
                                   "（tushare.db 锁冲突取不到收盘价），查面板日志")

        meta = c.execute("SELECT account_id, cash FROM strategy_accounts_meta ORDER BY account_id").fetchall()
        for aid, meta_cash in meta:
            a = acc.get(aid)
            if not a or a.get('total_nav') is None:
                continue
            _nr = c.execute("SELECT MAX(date) FROM strategy_accounts WHERE account_id=?", (aid,)).fetchone()
            if not _nr or not _nr[0] or (_last_td and str(_nr[0]) != str(_last_td)):
                continue                      # 冻结/销户：最后估值日≠本交易日（末行=清算日），面板显示清算值，设计内
            pos = c.execute("SELECT code, shares, avg_cost FROM strategy_positions WHERE account_id=?",
                            (aid,)).fetchall()
            _load_closes([p[0] for p in pos])
            _nav_calc = float(meta_cash or 0) + sum(s * close_map.get(cd, ac) for cd, s, ac in pos)
            _diff = (a.get('total_nav') or 0) - _nav_calc
            if abs(_diff) > max(200.0, abs(_nav_calc) * 0.005):
                issues_list.append(f"[对账][面板] {aid} nav不符: 面板{a.get('total_nav'):,.2f} "
                                   f"vs 复算{_nav_calc:,.2f}（差{_diff:+,.2f}）")
    except Exception as _e:
        issues_list.append(f"[对账][面板] 自检异常（未能完成比对）: {_e}")

# ── 8. 主账户 FIFO 断链（信息级，2026-09-17 新增）──
# 背景：主账户 trade_log 残缺——自 2026-07-20 起才有记录（7/7 建仓 16 笔买入 165.25 万、
# 7/19~7/31 多数加仓、8/4~8/14 丢的 SELL 都不在表内）→ 卖单配不到对应买入。
# 这类断链是**结构性的、每天都会存在**，所以不按问题推送（否则每晚都是假告警）；
# 处理：① 每次写 logs/main_fifo_gap.log 留痕；② 只有笔数比上次多才告警（说明又有成交没进流水表）。
def _fifo_gap():
    import collections
    from datetime import datetime as _dt
    _rows = c.execute("SELECT direction, code, quantity FROM trade_log "
                      "WHERE strategy IS NULL OR strategy='main' "
                      "ORDER BY REPLACE(COALESCE(trade_date,''),'-',''), COALESCE(id,0)").fetchall()
    _fifo = collections.defaultdict(list)
    for _dir, _code, _q in _rows:
        if _dir == 'BUY':
            _fifo[_code].append(int(_q or 0))
        else:
            _q = int(_q or 0)
            while _q > 0 and _fifo[_code]:
                _take = min(_q, _fifo[_code][0])
                _q -= _take
                if _fifo[_code][0] == _take:
                    _fifo[_code].pop(0)
                else:
                    _fifo[_code][0] -= _take
            if _q > 0:
                gap[0] += 1
    _log = BASE / 'logs' / 'main_fifo_gap.log'
    _log.parent.mkdir(exist_ok=True)
    _prev = None
    if _log.exists():
        for _line in _log.read_text(encoding='utf-8').splitlines()[::-1]:
            if '未配对卖出' in _line:
                try:
                    _prev = int(_line.split('未配对卖出')[1].split('笔')[0].strip())
                except Exception:
                    _prev = None
                break
    gap[1] = _prev
    with open(_log, 'a', encoding='utf-8') as _f:
        _f.write(f"{_dt.now():%Y-%m-%d %H:%M:%S}  未配对卖出 {gap[0]} 笔（上次 {_prev}）\n")
    if _prev is not None and gap[0] > _prev:
        issues.append(f"[对账][流水] 主账户未配对卖出由 {_prev} 增至 {gap[0]} 笔 → 又有成交未写入 trade_log"
                      f"（历史建仓期残缺属已知，增量说明新缺口，见 logs/main_fifo_gap.log）")

gap = [0, None]
try:
    _fifo_gap()
except Exception as _e:
    issues.append(f"[对账][流水] FIFO 断链自检异常: {_e}")

_panel_sanity(issues)

c.close()

# ── 输出: 正常静默，有问题才打 stdout（wrapper 据此推送 QQ） ──
if issues:
    print(f"每日对账发现 {len(issues)} 项问题:")
    for i in issues:
        print(" ", i)
    sys.exit(0)
