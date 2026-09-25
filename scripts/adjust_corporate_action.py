#!/usr/bin/env python3
"""除权除息账务调整（2026-09-04 建立，M2/MacBook 通用）

交易日盘前运行（cron 07:40）：查 tushare dividend(ex_date=今天) ∩ 各账户持仓，
对命中持仓做送转/派息账务调整，并把调整参数写入 ca_adjustments 表，
供 daily_report/server_dashboard 的收益反推做除权还原（否则除权日当日收益假亏）。

⚠️ 动机（用户 2026-09-04 拍板）：除权不调整 → 送转后股数不变、成本不摊薄 →
止损线(≈成本×0.88)失效：10送10 股价腰斩，开盘价 < 0.88×原成本 → 立即误触发硬止损清仓。

规则：
- 送转：shares = round(shares × (1 + stk_div + stk_bo_rate))，零股保留（真实券商允许）
- 派息：cash += shares × cash_div × (1 − 红利税率)；税率按 A 股持有期
  （除权日距买入日 ≤30 自然日 20%、≤365 日 10%、>365 日 0%；买入日缺失按 20% 保守）
- 成本回收法：avg_cost = (原总成本 − 净息) / 新股数（止损线随成本自然跟对；>0.01 clamp）
- 价格类（peak_price/target_price/stop_loss）按除权参考价同式下调：(v − cash_div) / factor，
  clamp ≥0.01（防除权日移动止盈/达目标价立即误触发）
- 配股（stk_co_rate>0）不自动处理 → 告警退出（需人工决策是否参与缴款）
- 只动账、不进 trade_log（非交易）；当日新买入自然按除权后价，不受影响
- 幂等：ca_adjustments 已有 (code, ex_date) → 跳过该股（防重复送转/派息）
- 数据库自动适配：主库含 trade_log（M2 state.db 单库）无前缀；否则 ATTACH ledger.db
  （MacBook v2）用 led. 前缀

用法：python3 -B scripts/adjust_corporate_action.py [--date YYYYMMDD] [--force] [--dry]
"""
import sys, json, sqlite3, argparse
from datetime import datetime, date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
STATE_DB = BASE / 'state.db'
SIM_DIR = BASE / 'sim_accounts'
# 策略账户列表动态发现（2026-09-04 修复：原静态 5 账户漏了 MacBook 的
# center_dual/agent_auto → 除权日不调账 = 原始止损误触发 bug 复发）。
# 规则：SIM_DIR 下 *.json，排除 main（主账户走 state.db holdings），
# 结构校验（含 positions list 与 cash）过滤 auto_trade_log 等非账户文件。
def discover_strat_accounts():
    accts = []
    if not SIM_DIR.exists():
        return accts
    for f in sorted(SIM_DIR.glob('*.json')):
        if f.stem == 'main':
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if isinstance(d.get('positions'), list) and 'cash' in d:
            accts.append(f.stem)
    return accts
CONFIG = json.load(open(BASE / 'config.json'))

# ── 运行窗口（2026-09-21 常量化 + 声明行，用户拍板）────────────────────
# 动机：MacBook 侧除权 cron 曾是 06:00，落在本窗口之外 → 每天 exit 0 静默跳过，
# 连续 5 个交易日无人发现（见 aquant-pipeline skill「2026-09-21 除权调整静默失效」）。
# ⚠️ 下面这行声明必须与实际生效的常量一致：~/.hermes/scripts/check_cron_window_alignment.py
#    会读它并与 cron 表达式交叉核对（不一致 → 健康检查告警），单测也校验二者一致。
# cron-window: 07:00-09:15,15:30-23:59
PRE_WINDOWS = (('07:00', '09:15'),)      # 盘前：cron 07:40 落此
POST_WINDOWS = (('15:30', '23:59'),)     # 盘后：手动/补跑窗口
WINDOW_DESC = ','.join(f'{lo}-{hi}' for lo, hi in PRE_WINDOWS + POST_WINDOWS)  # 与常量同源，防文案脱节


def is_in_window(hhmm):
    """hhmm='HH:MM' 是否落在任一允许窗口（闭区间，与 2026-09-04 起沿用的判据完全等价）"""
    return any(lo <= hhmm <= hi for lo, hi in PRE_WINDOWS + POST_WINDOWS)


def get_conn():
    """主账户账务连接，双机自适应：
    - MacBook v2：ledger.db（账本，含 trade_log/holdings）→ ATTACH 用 led. 前缀
      （其 BASE/state.db 是冻结旧单库，不能作为判据/写入目标）
    - M2 单库：state.db 即账本 → 无前缀"""
    led = BASE / 'ledger.db'
    if led.exists() and led.stat().st_size > 0:
        try:
            lc = sqlite3.connect(f'file:{led}?mode=ro', uri=True, timeout=5)
            tbls = [r[0] for r in lc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            lc.close()
            if 'trade_log' in tbls:
                conn = sqlite3.connect(str(STATE_DB), timeout=30)
                conn.execute("ATTACH DATABASE ? AS led", (str(led),))
                return conn, 'led.'
        except Exception:
            pass
    conn = sqlite3.connect(str(STATE_DB), timeout=30)
    return conn, ''


def table_names(conn, p=''):
    """列出表名。⚠️ 2026-09-21 修复：p 非空（ATTACH 前缀，如 MacBook 的 'led.'）时必须查
    `<p>sqlite_master` —— 裸 `sqlite_master` 只列 main schema，看不到 attach 进来的 ledger.db
    表 → has_db 误判 False → 只写 JSON 派生层、DB（权威源）不更新 → 下一轮 AccountStore.save
    用 DB 旧值重导 JSON，当天的派息/送转被静默回滚。"""
    src = f'{p}sqlite_master' if p else 'sqlite_master'
    # 返回**带前缀**的名字（p='led.' → 'led.strategy_positions'），与调用处 `p + 'strategy_positions'` 对齐；
    # p='' 时前缀为空 → 仍是裸名（M2 语义不变）
    return {f'{p}{r[0]}' for r in conn.execute(f"SELECT name FROM {src} WHERE type='table'").fetchall()}


def ensure_ca_table(conn, p):
    """ca_adjustments 按 (code, ex_date, account) 账户粒度记录（2026-09-04 复查改造：
    原每股一条（税率为 main 口径）→ audit 重放无法还原各策略账户真实净息。
    现每账户一行：factor/cash_div 全局同值，tax_rate/net_div/shares_add 按账户实际。"""
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {p}ca_adjustments (
        code TEXT NOT NULL,
        ex_date TEXT NOT NULL,
        account TEXT NOT NULL,
        factor REAL DEFAULT 1.0,
        cash_div REAL DEFAULT 0.0,
        tax_rate REAL DEFAULT 0.0,
        shares_add INTEGER DEFAULT 0,
        net_div REAL DEFAULT 0.0,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (code, ex_date, account)
    )""")
    # 运行戳（健康检查用：每日盘前是否成功执行）
    conn.execute(f"""CREATE TABLE IF NOT EXISTS {p}ca_run_log (
        run_date TEXT PRIMARY KEY,
        status TEXT,
        n_ex INTEGER,
        n_hit INTEGER,
        detail TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    )""")


def div_tax_rate(buy_date_raw, ex_date_raw):
    """A股差别化红利税：除权日距买入日 ≤30 自然日 20%，≤365 日 10%，>365 日 0%。
    买入日缺失按 20%（保守）。"""
    b = str(buy_date_raw or '').replace('-', '')
    if len(b) != 8:
        return 0.20
    try:
        bd = datetime.strptime(b, '%Y%m%d').date()
        ed = datetime.strptime(str(ex_date_raw).replace('-', ''), '%Y%m%d').date()
        days = (ed - bd).days
    except Exception:
        return 0.20
    if days > 365:
        return 0.0
    if days > 30:
        return 0.10
    return 0.20


def price_adj(v, cash_div, factor):
    """价格类按除权参考价下调：(v − cash_div) / factor；无值/越界 → clamp ≥0.01"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    f = factor if factor and factor > 0 else 1.0
    nv = (v - float(cash_div or 0)) / f
    return round(max(nv, 0.01), 3)


def get_ex_divs(pro, trade_date):
    """全市场当日除权列表 → {裸码: {stk_div, stk_bo_rate, cash_div, stk_co_rate}}"""
    df = pro.dividend(ex_date=str(trade_date))
    if df is None or len(df) == 0:
        return {}
    out = {}
    for _, r in df.iterrows():
        ts = str(r.get('ts_code') or '')
        if not ts or r.get('div_proc') != '实施':
            continue
        code = ts.split('.')[0]
        stk_div = float(r.get('stk_div') or 0) or 0.0
        stk_bo = float(r.get('stk_bo_rate') or 0) or 0.0
        stk_co = float(r.get('stk_co_rate') or 0) or 0.0
        cash_div = float(r.get('cash_div') or 0) or 0.0
        if stk_div <= 0 and stk_bo <= 0 and cash_div <= 0:
            continue
        out[code] = {'stk_div': stk_div, 'stk_bo': stk_bo, 'cash_div': cash_div, 'stk_co': stk_co}
    return out


def load_positions_main(conn, p):
    rows = conn.execute(
        f"SELECT code, shares, avg_cost, buy_date, target_price, stop_loss FROM {p}holdings "
        "WHERE status='hold'").fetchall()
    return {r[0]: {'shares': float(r[1]), 'avg_cost': float(r[2] or 0), 'buy_date': r[3],
                   'target': r[4], 'stop_loss': r[5]} for r in rows}


def adjust_main(conn, p, code, ex_date, par):
    """主账户（state.db holdings + account_balance + position_peaks）除权调整。
    返回 (净息, 调整说明, main税率) 或 None（无持仓）。ca_adjustments 由 run 统一管理。"""
    pos = load_positions_main(conn, p).get(code)
    if not pos or pos['shares'] <= 0:
        return None
    sh_old = pos['shares']
    ac_old = pos['avg_cost'] or 0
    factor = 1.0 + par['stk_div'] + par['stk_bo']
    tax = div_tax_rate(pos['buy_date'], ex_date)
    net_div = sh_old * par['cash_div'] * (1 - tax)
    sh_new = int(round(sh_old * factor)) if factor != 1.0 else int(sh_old)
    sh_new = max(sh_new, 1) if sh_old >= 1 else sh_new
    shares_add = sh_new - int(sh_old)
    total_cost = ac_old * sh_old
    total_cost_new = max(total_cost - net_div, 0.0)
    ac_new = round(total_cost_new / sh_new, 4) if sh_new > 0 else 0.0
    if ac_new < 0.01 and total_cost_new > 0:
        ac_new = 0.01
    # 价格类下调
    target_new = price_adj(pos['target'], par['cash_div'], factor)
    sl_new = price_adj(pos['stop_loss'], par['cash_div'], factor)
    # 峰值（position_peaks）
    peak_new = None
    pk = conn.execute(f"SELECT peak_price FROM {p}position_peaks WHERE code=?", (code,)).fetchone()
    if pk:
        peak_new = price_adj(pk[0], par['cash_div'], factor)
        conn.execute(f"UPDATE {p}position_peaks SET peak_price=?, updated_at=? WHERE code=?",
                     (peak_new, datetime.now().isoformat(), code))
    now = datetime.now().isoformat(timespec='seconds')
    conn.execute(
        f"UPDATE {p}holdings SET shares=?, avg_cost=?, stop_loss=?, target_price=?, "
        f"latest_price=ROUND(MAX((latest_price - ?) / ?, 0.01), 3), update_time=? "
        f"WHERE code=? AND status='hold'",
        (sh_new, ac_new,
         sl_new if sl_new is not None else round(ac_new * 0.88, 2),
         target_new if target_new is not None else 0.0,
         par['cash_div'], factor if factor != 1.0 else 1.0, now, code))
    # 现金入账（股息净额）
    if net_div > 0:
        conn.execute(f"UPDATE {p}account_balance SET cash_balance = cash_balance + ?, last_update=? "
                     "WHERE account_id='main'", (round(net_div, 2), now))
    notes = (f"送转x{factor:.3f} 派息{par['cash_div']:.4f}税{tax:.0%} "
             f"净息{net_div:,.0f} → {int(sh_old)}→{sh_new}股 @{ac_old}→{ac_new}")
    # 不在此 commit：由 run() 每股统一事务（失败可整体 rollback 防双倍）
    return round(net_div, 2), notes, tax, shares_add


def adjust_strategy(conn, p, aid, code, ex_date, par):
    """策略账户除权调整（2026-09-11 重写，表探测自适应）。返回 (净息, 说明, 税率, 增股) 或 None（无持仓）。

    09-11 修复的 bug：本函数原只写 sim_accounts/<id>.json，而 MacBook v2 的 strategy_accounts_daily 自
    08-27 DB-first 迁移后 cash/持仓的权威源是 ledger.db（meta+positions），每轮 save 会用
    DB 值重导 JSON → 派息被旧值盖掉（301055 +328 / 300818 +6.4 实损，对账 9/11 抓到）。
    09-11 双机兼容：M2 未做 DB-first（无 strategy_positions/strategy_accounts_meta 表，JSON 即权威源），
    故先探测表存在性——有 DB 表走 DB 权威写+JSON 同步导出；无则退回纯 JSON 写（M2 语义）。"""
    f = SIM_DIR / f'{aid}.json'
    tbls = table_names(conn, p)      # ⚠️ 必须带 ATTACH 前缀探测（2026-09-21 修复）
    has_db = (p + 'strategy_positions') in tbls and (p + 'strategy_accounts_meta') in tbls
    db_pos = conn.execute(
        f"SELECT shares, avg_cost, buy_date, peak_price, stop_loss, target FROM {p}strategy_positions "
        "WHERE account_id=? AND code=?", (aid, code)).fetchone() if has_db else None
    acct = json.load(open(f)) if f.exists() else None
    if db_pos is None:
        hit = [x for x in (acct.get('positions', []) if acct else []) if x.get('code') == code]
        if not hit or float(hit[0].get('shares') or 0) <= 0:
            return None
        db_pos = (hit[0]['shares'], hit[0]['avg_cost'], hit[0].get('buy_date'),
                  hit[0].get('peak_price'), hit[0].get('stop_loss'), hit[0].get('target'))
    sh_old, ac_old, buy_date, peak_old, sl_old, tgt_old = (float(db_pos[0] or 0), float(db_pos[1] or 0),
                                                           db_pos[2], db_pos[3], db_pos[4], db_pos[5])
    if sh_old <= 0:
        return None
    factor = 1.0 + par['stk_div'] + par['stk_bo']
    tax = div_tax_rate(buy_date, ex_date)
    net_div = sh_old * par['cash_div'] * (1 - tax)
    sh_new = int(round(sh_old * factor)) if factor != 1.0 else int(sh_old)
    sh_new = max(sh_new, 1) if sh_old >= 1 else sh_new
    shares_add = sh_new - int(sh_old)
    total_cost = ac_old * sh_old
    ac_new = round(max(total_cost - net_div, 0.0) / sh_new, 4) if sh_new > 0 else 0.0
    peak_new = price_adj(peak_old, par['cash_div'], factor)
    sl_new = price_adj(sl_old, par['cash_div'], factor)
    tgt_new = price_adj(tgt_old, par['cash_div'], factor)  # target 恒 0 时 price_adj 返回 None
    # ── DB 权威写（仅 DB-first 机器：MacBook v2 有 strategy_positions/meta）──
    # ⚠️ 2026-09-21 修复：原实现无条件执行这两条 UPDATE，而 M2 无这两张表 →
    #    命中持仓时必抛 "no such table: strategy_positions"（与参数缺失 bug 叠加，
    #    双重失效）。M2 语义 = 纯 JSON 写，必须整体跳过。
    if has_db:
        conn.execute(
            f"UPDATE {p}strategy_positions SET shares=?, avg_cost=?, peak_price=COALESCE(?,peak_price), "
            "stop_loss=COALESCE(?,stop_loss), target=COALESCE(?,target), updated_at=datetime('now','localtime') "
            "WHERE account_id=? AND code=?",
            (sh_new, ac_new, peak_new, sl_new, tgt_new, aid, code))
        conn.execute(
            f"UPDATE {p}strategy_accounts_meta SET cash = cash + ?, updated_at=datetime('now','localtime') "
            "WHERE account_id=?", (round(net_div, 2), aid))
    # ── JSON 导出层同步（有文件才同步，不新建） ──
    if acct is not None:
        for x in acct.get('positions', []):
            if x.get('code') == code:
                x['shares'] = sh_new
                x['avg_cost'] = ac_new
                if peak_new is not None: x['peak_price'] = peak_new
                if sl_new is not None: x['stop_loss'] = sl_new
                if tgt_new is not None: x['target'] = tgt_new
        acct['cash'] = round(float(acct.get('cash') or 0) + net_div, 2)
        tmp = f.with_name(f'{aid}.json.tmp')
        json.dump(acct, open(tmp, 'w'), ensure_ascii=False, indent=2)
        tmp.rename(f)
    notes = (f"送转x{factor:.3f} 派息{par['cash_div']:.4f}税{tax:.0%} "
             f"净息{net_div:,.0f} → {int(sh_old)}→{sh_new}股 @{ac_old}→{ac_new}")
    return round(net_div, 2), notes, tax, shares_add


def run(pro, trade_date, dry=False):
    """执行：查当日除权 ∩ 持仓 → 逐账户调整（每股一事务，各账户写 ca_adjustments 行）
    → 写运行戳。返回 summary list。"""
    divs = get_ex_divs(pro, trade_date)
    if not divs:
        conn, p = get_conn()
        ensure_ca_table(conn, p)
        conn.execute(f"INSERT OR REPLACE INTO {p}ca_run_log (run_date, status, n_ex, n_hit, detail) "
                     "VALUES (?,?,?,?,?)", (trade_date, 'ok', 0, 0, '全市场无除权除息股'))
        conn.commit()
        conn.close()
        return [f'{trade_date} 全市场无除权除息股']
    conn, p = get_conn()
    ensure_ca_table(conn, p)
    out = []
    # 全部账户持仓集合
    all_codes = set(load_positions_main(conn, p).keys())
    _tbls = table_names(conn, p)     # ⚠️ 必须带 ATTACH 前缀探测（2026-09-21 修复）
    if (p + 'strategy_accounts_meta') in _tbls:  # 09-11: M2 无 DB-first 表 → 从 JSON 收集（同旧语义）
        for aid, _cash in conn.execute(f"SELECT account_id, cash FROM {p}strategy_accounts_meta"):
            all_codes |= {r[0] for r in conn.execute(
                f"SELECT code FROM {p}strategy_positions WHERE account_id=?", (aid,))}
    else:
        for aid in discover_strat_accounts():
            f = SIM_DIR / f'{aid}.json'
            if f.exists():
                acct = json.load(open(f))
                for ps in acct.get('positions', []):
                    all_codes.add(ps.get('code'))
    hits = {c: v for c, v in divs.items() if c in all_codes}
    if not hits:
        conn.execute(f"INSERT OR REPLACE INTO {p}ca_run_log (run_date, status, n_ex, n_hit, detail) "
                     "VALUES (?,?,?,?,?)", (trade_date, 'ok', len(divs), 0, '与持仓无交集'))
        conn.commit()
        conn.close()
        return [f'{trade_date} 除权 {len(divs)} 只，与持仓无交集，无需调整']
    for code, par in sorted(hits.items()):
        if par['stk_co'] > 0:
            out.append(f"⚠️ {code} 今日配股(stk_co={par['stk_co']})：不自动处理，需人工决策")
            continue
        # 幂等：该股该日已有非 pending 账户行 → 已调整过跳过
        done = conn.execute(
            f"SELECT 1 FROM {p}ca_adjustments WHERE code=? AND ex_date=? AND account!='__pending__'",
            (code, trade_date)).fetchone()
        if done:
            out.append(f"⏭ {code} 已调整过（幂等跳过）")
            continue
        if dry:
            out.append(f"[DRY] {code}: 送转x{1+par['stk_div']+par['stk_bo']:.4f} "
                       f"派息{par['cash_div']} → 将调整持仓")
            continue
        # pending 占位防重入：中断/失败后保留，重跑会跳过（防双倍送转），
        # 人工核查补调后手动删 pending 行再重跑（见 except 分支说明）
        conn.execute(f"INSERT OR IGNORE INTO {p}ca_adjustments "
                     "(code, ex_date, account, factor, cash_div) VALUES (?,?,?,?,?)",
                     (code, trade_date, '__pending__', round(1+par['stk_div']+par['stk_bo'], 6),
                      par['cash_div']))
        conn.commit()
        try:
            factor = 1.0 + par['stk_div'] + par['stk_bo']
            hit_any = False
            r_main = adjust_main(conn, p, code, trade_date, par)
            if r_main:
                hit_any = True
                net_div, notes, tax, sh_add = r_main
                conn.execute(f"INSERT OR REPLACE INTO {p}ca_adjustments "
                             "(code, ex_date, account, factor, cash_div, tax_rate, shares_add, net_div) "
                             "VALUES (?,?,?,?,?,?,?,?)",
                             (code, trade_date, 'main', round(factor, 6), par['cash_div'], tax, sh_add,
                              round(net_div, 2)))
                out.append(f"  main: {notes}")
            for aid in discover_strat_accounts():
                # 2026-09-21 修复：签名 9/11 重写为 (conn, p, aid, code, ex_date, par)，
                # 调用处漏改 → 今日除权命中持仓时 TypeError，main/策略全部回滚，
                # 且 pending 占位残留 → 全天账务未调整（健康检查每 2h 告警）。
                r_s = adjust_strategy(conn, p, aid, code, trade_date, par)
                if r_s:
                    hit_any = True
                    net_div_s, notes_s, tax_s, sh_add_s = r_s
                    conn.execute(f"INSERT OR REPLACE INTO {p}ca_adjustments "
                                 "(code, ex_date, account, factor, cash_div, tax_rate, shares_add, net_div) "
                                 "VALUES (?,?,?,?,?,?,?,?)",
                                 (code, trade_date, aid, round(factor, 6), par['cash_div'], tax_s, sh_add_s,
                                  round(net_div_s, 2)))
                    out.append(f"  {aid}: {notes_s}")
            # 清理占位并统一提交（每股一个事务：main SQL 与占位同事务原子）
            conn.execute(f"DELETE FROM {p}ca_adjustments WHERE code=? AND ex_date=? AND account='__pending__'",
                         (code, trade_date))
            conn.commit()
            if hit_any:
                out.append(f"✅ {code} {trade_date} 除权调整完成")
            else:
                # 除权股在持仓集合但实际无账户持有（罕见：集合与调整间隙变动）
                conn.execute(f"DELETE FROM {p}ca_adjustments WHERE code=? AND ex_date=? AND account='__pending__'",
                             (code, trade_date))
                conn.commit()
                out.append(f"ℹ️ {code} {trade_date} 无实际持仓账户，跳过")
        except Exception as e:
            conn.rollback()
            # pending 占位保留（防重跑双倍送转）——main SQL 已随 rollback 还原，json 已写账户需人工核查
            out.append(f"❌ {code} 调整失败: {e} → 已回滚 SQL；部分 json 可能已写，"
                       "请人工核查后手动删除 ca_adjustments 中该股 __pending__ 行再重跑")
            conn.commit()
    # 运行戳（⚠️ 2026-09-21：dry 是演练模式，不写戳 —— 否则健康检查把"只演练、未调整"
    # 读成 status=ok 已调整，静默掩盖真实失败。MacBook 9/21 的 09:33 手动 --dry 就是这么
    # 把当天 06:00 空跑的真实结果覆盖掉的。）
    if not dry:
        _has_err = any('❌' in l for l in out)
        conn.execute(f"INSERT OR REPLACE INTO {p}ca_run_log (run_date, status, n_ex, n_hit, detail) "
                     "VALUES (?,?,?,?,?)",
                     (trade_date, 'error' if _has_err else 'ok', len(divs), len(hits), '；'.join(out)[:500]))
    conn.commit()
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='除权日 YYYYMMDD（默认今天）')
    ap.add_argument('--force', action='store_true', help='允许非盘前窗口运行（手动/测试）')
    ap.add_argument('--dry', action='store_true', help='只打印不调整')
    args = ap.parse_args()
    td = args.date or datetime.now().strftime('%Y%m%d')
    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：休市日无除权事件，不跑账务调整
    if not args.date and not args.force and not args.dry:
        from core.trade_calendar import assert_trading_day
        assert_trading_day('除权调整')
    # 盘前窗口保护：仅允许窗口内运行（交易时段禁止，防与盘中并发写账）
    # 窗口常量与声明行见文件上方 PRE_WINDOWS/POST_WINDOWS + `# cron-window:`
    if not args.force and not args.dry:
        hhmm = datetime.now().strftime('%H:%M')
        if not is_in_window(hhmm):
            print(f'⏭ 当前 {hhmm} 不在允许窗口 {WINDOW_DESC} 内 → 跳过除权调整（防与盘中并发写账）。'
                  f'若这是 cron 触发的，说明该 job 时刻落在窗口外：跑 '
                  f'~/.hermes/scripts/check_cron_window_alignment.py 核对（人工补跑加 --force）。')
            sys.exit(0)
    try:
        import tushare as ts
        ts.set_token(CONFIG.get('tushare_token', ''))
        pro = ts.pro_api()
    except Exception as e:
        print(f'❌ tushare 初始化失败: {e}')
        sys.exit(1)
    for line in run(pro, td, dry=args.dry):
        print(line)
    print(f'[adjust_corporate_action] {td} 完成')


if __name__ == '__main__':
    main()
