#!/usr/bin/env python3
"""三策略独立模拟账户 (2026-08-02 建立)
为三因子融合 / CMMR / CMMR+融合 各开一个独立模拟账户，跟踪实际买卖收益。

账户语义（真实交易约束，2026-08-02 用户要求）：
- 禁止非交易时段买卖 + 必须按实时价格成交 + 新账户从 20260803 才开始交易
- 每日盘中（cron 10:00）运行：用最近一个"早于今天"的信号日的信号（盘后信号），
  以 Sina 实时价格成交（买入/卖出），NAV 按实时价估值
- 脚本只在交易时段执行（9:30-11:30 / 13:00-15:00），非交易时段/节假日/停牌自动跳过
- --init 历史回放模式例外：用日线 open/close 补算历史（无实时价可用）

账户配置：
- fusion3f     : fusion_3f_signals  signal='强买'，fusion_3f_score DESC, flow_alpha DESC
- cmmr         : signal_history     cmmr_score > 0，cmmr_score DESC
- cmmr_fusion  : signal_history     fusion_score_cmmr 当日 top15%（百分位 p85），按分 DESC

状态：AccountStore JSON (sim_accounts/<id>.json) + ledger.db.strategy_accounts NAV 表

用法：
  python3 -B scripts/strategy_accounts_daily.py            # 交易时段内执行实时价调仓（幂等）
  python3 -B scripts/strategy_accounts_daily.py --report   # 只输出当前对比报告
"""
import sqlite3
import duckdb
import numpy as np
import sys
import subprocess
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from core.unified_account import AccountStore, Account, Position, Trade
from core.prices import fetch_prices_batch, fetch_price_live, fetch_price_open
import cooldown  # 卖出冷却+止损记忆（2026-09-01：时间/价格/模型三腿）
from core import defense  # 防御状态机（2026-09-16 用户拍板"挂上"：halved/crash2 两档，见 core/defense.py）

STATE_DB = _SCRIPT_DIR / 'ledger.db'      # v2热层: strategy_accounts/crash_state/trade_log
SIGNALS_DB = _SCRIPT_DIR / 'signals.db'  # v2温层: 信号/因子表(ATTACH为sig)
TUSHARE_DB = _SCRIPT_DIR / 'tushare.db'
INIT_CAPITAL = 1_000_000.0
TOP_N = 10
MIN_BUY_AMOUNT = 2000.0  # 单笔最小买入金额（2026-08-28 聚合门槛：碎仓防新增——零钱不足 2000 不摊，攒够再买；现金够时按"能买几只买几只"满额分配）
MIN_POSITION_RATIO = 0.025  # 最小建仓权重 = 总资产 2.5%（2026-09-21 用户拍板：防碎仓。实际门槛 =
                            #   max(MIN_BUY_AMOUNT, NAV×2.5%)，取代原来固定 2000 元（仅 0.18% NAV）。
                            #   口径与主账户 intraday_decision.MIN_POSITION_RATIO 对齐）
# 止盈(R6 回撤止盈)卖出后禁买回交易日数——单一来源 cooldown.py（主账户/策略账户共用，
# 2026-09-02 用户拍板）。N=1 = 仅卖出当日禁、次日若仍上榜可由买入逻辑接回；"禁几天"待定后改 cooldown.py。
TP_REENTRY_BAN_DAYS = cooldown.TP_REENTRY_BAN_DAYS
# 账户最早可交易日期（用户 2026-08-02 要求：新账户明天才开始交易，禁止历史回放建仓）
START_DATE = '20260803'

# 重评间隔默认值：10 个交易日（2026-08-03 信号-执行匹配，10d 信号窗口期）
# ⚠️ 只作「未在 ACCOUNTS 显式配 rebalance 的账户」兜底；中枢版/中枢+三模型 2026-09-11 起 = 20 日。
#    改重评窗口 → 只改 ACCOUNTS[aid]['rebalance']（单一来源；daily_report 直接读本字典显示）
REBALANCE_INTERVAL = 10

# 碎仓清理阈值（2026-09-11 用户拍板）：重评日卖出"权重 < 1% 且不在新 top10"的残留小仓
DUST_CLEAN_RATIO = 0.01

# 止损三档（2026-08-31 用户拍板：尾盘确认 + 加速档 + 硬止损无条件）
HARD_STOP_FLOOR = 0.88     # R5 硬止损 -12%：无条件立即卖（尾部风险防线，不等尾盘，抢跌停前）
ACCEL_STOP_FLOOR = 0.91    # 加速止损 -9%：从 -6% 继续恶化到 -9% = 非假摔，无条件立即卖
FLOAT_STOP_FLOOR = 0.94    # R7 浮亏止损 -6%：开盘破位（隔夜利空）立即卖；否则 14:30 尾盘确认
# ⚠️ 2026-09-16 防御状态机（用户拍板"挂上"，core/defense.py）：halved/crash2 模式下
#    R7 收紧到 -5%、新开仓×0.5、fusion<3 清出、大跌次日减至5成仓。运行期一律用
#    defense.float_stop(DMODE) 取地板，勿直接用本常量。
DMODE = 'normal'  # 防御状态（2026-09-16 挂上）：main() 每场评估一次后覆盖，run_day/topup_gap 共用
STOP_CONFIRM_TIME = '14:30'  # 浮亏止损尾盘确认时间（当日 77% 止损单卖完即反弹，早盘假摔多）

ACCOUNTS = {
    # ⚠️ 2026-09-11 全体策略账户统一 topup='gap'（每日补仓只补"已持有目标仓"的等权缺口，
    # 不买未持有的新票）→ 组合严格 = 重评日 top10 等权；存量碎仓由重评日碎仓清理(1%)清掉。
    # 回滚：把 topup 改成 'all'。
    # 2026-09-11 销户（用户拍板"直接取消三因子系的账户"）：09-06 面板IC口径审计实锤
    # 三因子直选 f3f 全截面 IC -0.115 / 子集内 -0.071 / Top10 跑输市场（五信号唯一两侧全负），
    # dual 子集内 +0.176 但 Top10≈打平——两账户无独立存在价值。closed=True → 交易循环与
    # 冷却归档跳过，NAV/持仓冻结保留在 DB（fusion3f 23笔、fusion_dual 32笔，NAV 止于 20260910）。
    # 回滚：删 closed 键即恢复交易。
    'fusion3f': {'name': '三因子融合', 'src': 'fusion_3f', 'topup': 'gap', 'closed': True},
    # rebalance=10（2026-09-20 用户拍板 20→10，**仅 cmmr 一账户**，cmmr_fusion 维持 20）：
    # 09-11 换 20d 的依据（fusion 次级键 13/13
    # 天跑赢）经配对差分复核为"对池均值"口径虚高（_cmmr_deepdive_0920.py：top10 vs 池内
    # 随机10 配对差仅 +0.29% t+0.91）。20d 无支持证据、10d 有：80+ top10 前10天段超额
    # +5.17%/批(t+11.4)，10→20段超额 -1.23%(t-12.0)；第10天换新票 vs 旧票续持 +2.57%/批
    # (t+14.1, 13/19)，新旧 top10 重叠仅 0.1/10=池本身高换手。脚本 _cmmr_marginal_leg_0920.py
    # /_cmmr_swap_verdict_0920.py/_cmmr_window_rollo_0920.py。注意：三检验 top10 键序均为
    # cmmr DESC + fusion DESC（贴 cmmr_fusion 选池口径），证据归属两账户共享；fusion 侧
    # 维持 20 系另一理由（20d 信号窗对齐），见下行。回滚=改回 20，备份
    # .bak.20260920_cmmr10d。（旧注 09-11：原默认10→20 系"证据窗口错配"论，已废）
    'cmmr': {'name': 'CMMR独立', 'src': 'cmmr', 'rebalance': 10, 'topup': 'gap'},
    # rebalance=20（09-20 用户维持，理由：该账户绑 fusion 次级键，融合模型（reg20/40）
    # 信号窗口本身是 20d，持有窗与信号窗对齐）
    'cmmr_fusion': {'name': 'CMMR+融合', 'src': 'cmmr_fusion', 'rebalance': 20, 'topup': 'gap'},
    # 2026-09-21 新增（用户拍板"直接开个cmmr+clf10账户来验证"）：现行 cmmr 选池
    # （cmmr_score>=80 地板 + fusion 次级键）之上加第二道门票 clf10 截面分位>=70。
    # 依据 _cron_clf_gate_cmmr_0921.py（19 有分日配对）：fwd10 +1.70pp t+1.42 p0.15、
    # fwd20 +1.58pp t+1.57 p0.12，双窗同向但未过显著线——故走模拟账户实盘对拍而非直接改 cmmr。
    # rebalance=10 与母账户 cmmr 同（A70 对拍按 10 日窗口做的），与 cmmr 逐批可比。
    # clf10 无分日（8/12 前/缺数）门票不生效=退化为母池，宁可同日可比不悬空。
    # 回滚：加 'closed': True 冻结。
    'cmmr_clf': {'name': 'CMMR+clf门票', 'src': 'cmmr_clf', 'rebalance': 10, 'topup': 'gap'},
    # 2026-08-06 新增：中枢版融合（三因子倒U信息中枢化，17年样本外 IC +0.060 t=+37），独立信号不改 fusion_3f_engine
    # rebalance=20（2026-09-11 用户拍板 10→20）：17 年 3814 交易日非重叠网格，10 日只吃到
    # 40 日累积毛 alpha 的 44%；成本减半后净/日 +0.0074→+0.0114、正年数 11/17→15/17
    # （滑点 0.2%/边假设下 10 日口径转负、20 日仍正）。证据 stockdb/reports/20260911_rebal20_handoff.md。
    # 切换平滑：不动 last_rebalance_date，下次重评由「第 10 个交易日」变为「第 20 个交易日」触发。
    'fusion_center': {'name': '中枢版Top10', 'src': 'fusion_center', 'rebalance': 20, 'topup': 'gap'},
    # 2026-09-06 新增：三因子融合+三模型融合 组合策略（双信号当日横截面百分位等权平均）
    # 2026-09-11 销户（与 fusion3f 同批，用户"三因子系的两个账户没存在必要"）：三因子腿 IC 为负
    # 拖累组合（dual 全截面 +0.176 但 Top10 执行子集≈打平大盘，挣不到钱），同 fusion3f 处置。
    'fusion_dual': {'name': '三因子+三模型', 'src': 'fusion_dual', 'topup': 'gap', 'closed': True},
    # 2026-08-27 新增：中枢版+三模型融合（fusion_center 倒U中枢 score + 三模型 fusion_score
    # 双信号当日横截面百分位等权平均，同 fusion_dual 算法；rebalance 15 跟随双信号组合口径）
    # rebalance=20（2026-09-11 用户拍板 15→20）：⚠️ 证据为**外推**——中枢腿本身 20–40 日
    # （17 年网格支持）+ 三模型腿 40 日预测窗，两腿同向；组合自身无独立历史证据
    # → 改后挂滚动 IC 监控，30 个成熟交易日后复核（见 references/center-dual-17y-and-account-20260911.md）。
    'center_dual': {'name': '中枢版+三模型', 'src': 'center_dual', 'rebalance': 20, 'topup': 'gap'},
    # 2026-09-04 新增：Agent全权账户（用户拍板：agent 全权买卖，不走机械 rebalance、
    # 不挂主账户风控）。manual=True → 本脚本对它只更新 NAV 估值，绝不动持仓；
    # 交易由 scripts/agent_trade_decision.py（cron 唤起 agent 裁决）执行。
    # 信号源与 center_dual 同款（中枢版+三模型百分位等权），候选池取前 15。
    'agent_auto': {'name': 'Agent全权', 'src': 'agent_auto', 'manual': True},
    # 2026-09-15 新增（用户拍板"开"）：10d 独立账户——reg10 此前无仓位消费（fusion 公式
    # 20/30/50 中实际贡献≈0.08%，09-10 复核）。执行端对拍（30 成熟信号日 top10 篮子 10 日
    # 实际收益，_q_exec10_variants_0915.py）：reg10 纯排 +9.72%（正天 25/28）> clf10 纯排
    # +7.48% > fusion 腿 +6.08%（正天 18/28）> 全池等权 +2.91%——reg10 是全系统执行端最强
    # 信号，头部篮子超额 fusion 腿 6.8pp。rebalance=10 = 证据窗口本身（10 日持有重评），
    # 不跟随 09-11 的 20 日切换（那是 cmmr/中枢系证据，与 reg10 的 10 日口径错配）。
    # 回滚：加 'closed': True 即冻结 NAV/持仓停交易。
    'reg10_solo': {'name': '10d独立', 'src': 'reg10', 'rebalance': 10, 'topup': 'gap'},
}


def ts_code(code):
    code = str(code)
    return f'{code}.SH' if code.startswith(('6', '68', '9')) else f'{code}.SZ'


def ensure_nav_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_accounts (
            account_id TEXT NOT NULL,
            date TEXT NOT NULL,
            nav REAL, cash REAL, pos_value REAL,
            daily_ret REAL, market_ret REAL, n_pos INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (account_id, date)
        )
    """)
    # 大跌市状态表（2026-08-18 新增：尾盘确认大跌市 + 次日防御延续）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_crash_state (
            crash_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def get_filtered_codes(tushare):
    """返回应剔除的代码集（ST/退市/北交所）"""
    bad = set()
    try:
        rows = tushare.execute(
            "SELECT ts_code, name, market FROM stock_basic"
        ).fetchall()
        for ts, name, market in rows:
            if name and ('ST' in name or '退' in name):
                bad.add(ts)
            if market == '北交所' or (ts and ts.startswith(('8', '4', '92'))):
                bad.add(ts)
    except Exception:
        pass
    return bad


def get_signal_targets(state, tushare, d, src, bad_codes, top_n=10):
    """返回信号日 d 的目标 topN（裸码+分数，不过滤价格——实时价过滤在 run_day 做）
    top_n=10 买入（重评日整仓重建基准；B方案 2026-08-04 删除 top20 卖出边界，见 run_day）"""
    if src == 'fusion_3f':
        rows = state.execute("""
            SELECT stock_code, fusion_3f_score, flow_alpha FROM sig.fusion_3f_signals
            WHERE REPLACE(date,'-','')=? AND signal='强买'
            ORDER BY fusion_3f_score DESC, flow_alpha DESC
        """, (d,)).fetchall()
        picks = [(r[0], float(r[1])) for r in rows]
    elif src == 'cmmr':
        # 2026-09-06 用户拍板：买入地板 cmmr_score>=80（原>0）。
        # 依据：档位路径研究(_cmmr_grade_path_0906.py, 9成熟20d窗口)——20-40分档20d超额
        # -3.89%且20天内从未转正=接刀池；60-80档+4.32%、100档+4.83%。80+供应历史最少
        # 日(8/11)也有28只>10只目标，正常市况零影响；极端缩量时宁持币不接刀。
        # 2026-09-11 修同分抽签：cmmr_score 离散6档，80+ 大量并列（9/11 有 189 只并列80、
        # 57 只并列100），原 ORDER BY 单键取 top10 = 同分内部按 rowid 抽签，选池不可复现。
        # 次级排序键=fusion_score（三模型融合原始分，连续值）。依据
        # _cmmr80_tiebreak_evidence_0911.py：13 个成熟20d日，80+ 档内按 fusion_score
        # 劈两半，高半 13/13 天跑赢低半，日均差 +5.39pp——档内该分有真实区分度。
        rows = state.execute("""
            SELECT stock_code, cmmr_score FROM sig.signal_history
            WHERE REPLACE(date,'-','')=? AND cmmr_score >= 80
            ORDER BY cmmr_score DESC, COALESCE(fusion_score, 0) DESC, stock_code
        """, (d,)).fetchall()
        picks = [(r[0], float(r[1])) for r in rows]
    elif src == 'cmmr_clf':  # cmmr_clf（2026-09-21 新增，验证账户）
        # 母池=cmmr 现行键序（80地板+fusion次级键），第二门票=clf10 当日截面分位>=70。
        # clf10 无分（当日影子链缺数）→ 门票跳过、退化为母池（可比性优先，_cron_clf_gate_cmmr_0921.py 同口径）。
        rows = state.execute("""
            SELECT stock_code, cmmr_score FROM sig.signal_history
            WHERE REPLACE(date,'-','')=? AND cmmr_score >= 80
            ORDER BY cmmr_score DESC, COALESCE(fusion_score, 0) DESC, stock_code
        """, (d,)).fetchall()
        clf = {str(r[0]): float(r[1]) for r in state.execute(
            "SELECT code, score FROM sig.shadow_clf10_scores WHERE date=?", (d,)).fetchall()}
        if len(clf) >= 100:
            thr = float(np.percentile(sorted(clf.values()), 70))
            rows = [(c, s) for c, s in rows if clf.get(str(c), 1.0) >= thr]
        picks = [(r[0], float(r[1])) for r in rows]
    elif src == 'cmmr_fusion':  # cmmr_fusion
        rows = state.execute("""
            SELECT stock_code, fusion_score_cmmr FROM sig.signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score_cmmr IS NOT NULL AND fusion_score_cmmr > 0
        """, (d,)).fetchall()
        scores = sorted(float(r[1]) for r in rows)
        n = len(scores)
        p85 = scores[int(n * 0.85)] if n > 0 else 0
        picks = sorted(
            [(r[0], float(r[1])) for r in rows if float(r[1]) >= p85],
            key=lambda x: x[1], reverse=True)
    elif src == 'fusion_center':
        # 中枢版融合 top10（2026-08-06 新增：三因子倒U信息中枢化，17年样本外 IC +0.060 t=+37）
        rows = state.execute("""
            SELECT stock_code, score FROM sig.fusion_center_signals
            WHERE REPLACE(date,'-','')=? AND signal='强买'
            ORDER BY score DESC
        """, (d,)).fetchall()
        picks = [(r[0], float(r[1])) for r in rows]
    elif src == 'fusion_dual':  # 三因子融合 + 三模型融合（2026-08-10 新增）
        # 双信号当日横截面百分位等权平均：0.5*pct(fusion_3f_score) + 0.5*pct(fusion_score)
        # 消除两套信号量纲差异（三因子 0-100 百分位分 vs 三模型原始预测分加权和）
        f3_rows = state.execute("""
            SELECT stock_code, fusion_3f_score FROM sig.fusion_3f_signals
            WHERE REPLACE(date,'-','')=? AND fusion_3f_score IS NOT NULL
        """, (d,)).fetchall()
        md_rows = state.execute("""
            SELECT stock_code, fusion_score FROM sig.signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
        """, (d,)).fetchall()
        f3map = {r[0]: float(r[1]) for r in f3_rows}
        mdmap = {r[0]: float(r[1]) for r in md_rows}
        common = sorted(set(f3map) & set(mdmap))
        if not common:
            picks = []
        else:
            n = len(common)
            f3_rank = np.argsort(np.argsort([f3map[c] for c in common])) + 1
            md_rank = np.argsort(np.argsort([mdmap[c] for c in common])) + 1
            comb = {c: 0.5 * f3_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                    for i, c in enumerate(common)}
            # 强买 = 组合分前 15%（与 fusion_3f 强买口径一致）
            th = float(np.percentile(list(comb.values()), 85))
            picks = sorted([(c, s) for c, s in comb.items() if s >= th],
                           key=lambda x: x[1], reverse=True)
    elif src == 'reg10':
        # 2026-09-15 新增（10d独立账户）：reg10 纯排序，无地板阈值。
        # 依据：30 成熟日执行端对拍 reg10 纯排 +9.72%（正天 25/28）断层第一，
        # clf10 否决（<0.50 / <P30）实测 -2.6~-2.7pp（t≈-2.9）为负作用 → 不加否决。
        # reg10 为小数口径（如 0.105=10.5% 预期涨幅），排序只用相对序。
        rows = state.execute("""
            SELECT stock_code, reg10 FROM sig.signal_history
            WHERE REPLACE(date,'-','')=? AND reg10 IS NOT NULL
            ORDER BY reg10 DESC, stock_code
        """, (d,)).fetchall()
        picks = [(r[0], float(r[1])) for r in rows]
    elif src in ('center_dual', 'agent_auto'):  # 中枢版 + 三模型融合（2026-08-27 新增；2026-09-04 agent_auto 复用同款口径）
        # 双信号当日横截面百分位等权平均：0.5*pct(fusion_center score) + 0.5*pct(fusion_score)
        # 同 fusion_dual 算法，把三因子换成中枢版倒U中枢 score
        ct_rows = state.execute("""
            SELECT stock_code, score FROM sig.fusion_center_signals
            WHERE REPLACE(date,'-','')=? AND score IS NOT NULL
        """, (d,)).fetchall()
        md_rows = state.execute("""
            SELECT stock_code, fusion_score FROM sig.signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
        """, (d,)).fetchall()
        ctmap = {r[0]: float(r[1]) for r in ct_rows}
        mdmap = {r[0]: float(r[1]) for r in md_rows}
        common = sorted(set(ctmap) & set(mdmap))
        if not common:
            picks = []
        else:
            n = len(common)
            ct_rank = np.argsort(np.argsort([ctmap[c] for c in common])) + 1
            md_rank = np.argsort(np.argsort([mdmap[c] for c in common])) + 1
            comb = {c: 0.5 * ct_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                    for i, c in enumerate(common)}
            # 强买 = 组合分前 15%（与 fusion_3f 强买口径一致）
            th = float(np.percentile(list(comb.values()), 85))
            picks = sorted([(c, s) for c, s in comb.items() if s >= th],
                           key=lambda x: x[1], reverse=True)
    # 过滤 ST/北交所（价格过滤在 run_day 用实时价做）
    # 2026-08-08 TDX 尾盘急拉过滤（执行端接入, 用户批准）:
    # 只排除 VWAP正偏的尾盘急拉（>1.5%）——高位出货式拉升, 次日中位-1.32% (n=9080)
    # VWAP非正偏的急拉 = 补涨式拉升, 次日+0.43% (n=1874) → 不排除
    # 诱多组合(08-08): 开跌+vwap高+振幅大 → 次日-0.61% (n=23504) → 排除
    tail30, tail5, entrap = {}, {}, set()
    try:
        tail30 = {r[0]: r[1] for r in state.execute(
            "SELECT code, tail30_ret FROM sig.tdx_intraday_feat WHERE date=? AND tail30_ret > 0.015 AND vwap_dev > 0", (d,)).fetchall()}
        # 2026-09-02 分钟线挖掘新增: 最后5分钟急拉>1.5%（不看VWAP）, 次日中位-1.23%, 5/5月为负
        tail5 = {r[0]: r[1] for r in state.execute(
            "SELECT code, tail5_ret FROM sig.tdx_intraday_feat WHERE date=? AND tail5_ret > 0.015", (d,)).fetchall()}
        entrap = {r[0] for r in state.execute(
            "SELECT code FROM sig.tdx_intraday_feat WHERE date=? AND open30_ret < 0 AND vwap_dev > 0 AND amp_intra > 0.05", (d,)).fetchall()}
    except Exception:
        pass
    out = []
    log_date = datetime.now().strftime('%Y-%m-%d')
    for code, score in picks:
        ts = ts_code(code)
        if ts in bad_codes:
            continue
        if code in tail30:
            print(f"  ⏭ {code} 信号日尾盘急拉 {tail30[code]*100:+.1f}% 且VWAP正偏 → 跳过（出货式拉升, 次日中位-1.32%）")
            try:
                state.execute("INSERT INTO tdx_signal_log (log_date, signal_date, code, signal_type, action, price, account) VALUES (?,?,?,?,?,?,?)",
                              (log_date, d, code, 'excluded_tail', 'EXCLUDE', None, src))
                state.commit()
            except Exception:
                pass
            continue
        if code in tail5:
            print(f"  ⏭ {code} 信号日最后5分钟急拉 {tail5[code]*100:+.1f}% → 跳过（尾盘突击诱多, 次日中位-1.23%, 5/5月为负）")
            try:
                state.execute("INSERT INTO tdx_signal_log (log_date, signal_date, code, signal_type, action, price, account) VALUES (?,?,?,?,?,?,?)",
                              (log_date, d, code, 'excluded_tail5', 'EXCLUDE', None, src))
                state.commit()
            except Exception:
                pass
            continue
        if code in entrap:
            print(f"  ⏭ {code} 诱多组合(开跌+VWAP高+振幅大) → 跳过（次日中位-1.09%）")
            try:
                state.execute("INSERT INTO tdx_signal_log (log_date, signal_date, code, signal_type, action, price, account) VALUES (?,?,?,?,?,?,?)",
                              (log_date, d, code, 'excluded_entrap', 'EXCLUDE', None, src))
                state.commit()
            except Exception:
                pass
            continue
        out.append((code, score))
    return out[:top_n]


def market_ret_realtime():
    """市场基准：中证1000实时涨跌幅%（2026-08-05 从上证改为中证1000——
    策略账户持仓以中小盘为主，上证权重股主导会高估超额；中证1000 更匹配风格）"""
    try:
        px, chg = fetch_price_live('000852')
        return round(chg, 4) if px else 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────
# 大跌市判定（2026-08-18 新增，用户拍板：非大跌市必须满仓运作）
# 定义（尾盘确认版）：
#   当日 14:30 后，中证1000 实时跌幅 ≤ CRASH_THRESHOLD(-3%) → 确认大跌市
#   次日防御延续：昨日确认大跌市 且 今日中证1000 未收复（实时 ≤ -1.5%）→ 继续停买
#   尾盘确认的意义：早盘 -3% 可能低开高走（假摔），不立即停买；尾盘确认是真跌
#   止损止盈在持仓侧兜底（R5硬止损/R6回撤止盈），此处只管买入侧（不新增仓位）
# ─────────────────────────────────────────────────────────────
CRASH_THRESHOLD = -3.0    # 当日尾盘确认大跌市的跌幅阈值（%）
CRASH_RECOVER = -1.5      # 次日视为"未收复"的阈值（%）：实时 ≤ 此值继续防御
CRASH_CONFIRM_TIME = '14:30'  # 尾盘确认起始时间
OPEN_WEAK_THRESHOLD = -1.5    # 开盘方向过滤阈值（%，2026-08-19 方案C）
OPEN_WEAK_UNTIL = '10:00'     # 开盘观察期截止时间（9:30-10:00）
TREND_DROP_DAYS = 3           # 趋势窗口：近 N 交易日（2026-08-19 维度2）
TREND_DROP_THRESHOLD = -4.0   # 近3日累计跌幅阈值：≤-4% 视为下跌趋势（慢熊保护）

def _crash_state_from_db(state):
    """读 ledger.db 的 crash 状态（昨日是否确认大跌市）"""
    try:
        r = state.execute(
            "SELECT crash_date FROM strategy_crash_state ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return r[0] if r else None
    except Exception:
        return None

def _set_crash_state(state, crash_date):
    """写 ledger.db 的 crash 状态（幂等：同日期只留一行）"""
    try:
        state.execute("DELETE FROM strategy_crash_state")
        state.execute("INSERT INTO strategy_crash_state (crash_date) VALUES (?)", (crash_date,))
        state.commit()
    except Exception:
        pass

def is_crash_market(state, trade_date, market_ret=None):
    """大跌市判定（尾盘确认版 + 早盘急跌保护，2026-08-19 方案B）：
    - 早盘急跌保护（新增）：中证1000 实时 ≤-3% 且 现价 ≤ 开盘价（持续走弱非低开高走）
      → 立即停买（不等 14:30，防暴跌日接飞刀；8/19 实盘：-4.42% 暴跌日早盘重评买入后
      下午空窗期仍可能补仓——本保护堵住该窗口）
    - 低开高走豁免：现价 > 开盘价（从开盘回升）→ 不触发早盘保护，等 14:30 尾盘确认（防假摔）
    - 尾盘确认：14:30 后实时 ≤-3% → 确认大跌市，写状态，停买
    - 次日防御延续：昨日确认 且 今日实时 ≤-1.5%（未收复）→ 继续停买；收复则恢复
    返回 (是否停买, 原因)"""
    now_ts = datetime.now().strftime('%H:%M:%S')
    if market_ret is None:
        market_ret = market_ret_realtime()

    # 昨日大跌市状态
    last_crash = _crash_state_from_db(state)
    if last_crash:
        if market_ret <= CRASH_RECOVER:
            return True, f'昨日大跌市({last_crash})未收复(实时{market_ret:+.2f}%≤{CRASH_RECOVER}%)，防御停买'
        else:
            _set_crash_state(state, None)  # 收复，清状态
            return False, f'昨日大跌市已收复(实时{market_ret:+.2f}%)，恢复买入'

    # 早盘急跌保护（14:30 前生效）：≤-3% 且 现价≤开盘价（持续走弱）→ 立即停买
    # 低开高走（现价>开盘价）→ 豁免，走尾盘确认
    if now_ts < CRASH_CONFIRM_TIME and market_ret <= CRASH_THRESHOLD:
        try:
            open_px = fetch_price_open('000852')
            if open_px:
                cur_px = fetch_price_live('000852')[0]
                if cur_px and cur_px <= open_px:
                    _set_crash_state(state, trade_date)
                    return True, f'早盘急跌(中证1000 {market_ret:+.2f}%≤{CRASH_THRESHOLD}% 且现价≤开盘持续走弱)，停买'
                # 低开高走：现价>开盘 → 豁免
        except Exception:
            pass  # 拿不到开盘价则退化为等尾盘确认

    # 尾盘确认（14:30 后）
    if now_ts >= CRASH_CONFIRM_TIME:
        if market_ret <= CRASH_THRESHOLD:
            _set_crash_state(state, trade_date)
            return True, f'尾盘确认大跌市(中证1000 {market_ret:+.2f}%≤{CRASH_THRESHOLD}%)，停买'
    return False, f'非大跌市(中证1000 {market_ret:+.2f}%)，正常买入'


def is_open_weak(market_ret=None):
    """开盘方向过滤（2026-08-19 方案C，用户拍板）：
    9:30-10:00 观察期内，中证1000 实时 ≤ OPEN_WEAK_THRESHOLD(-1.5%) → 该轮跳过买入，
    等下一轮（10 分钟后再判）——避免开盘 30 分钟方向未明时无脑成交（8/19 案例：
    9:30 重评买入时指数仅小幅下跌，全天收 -4.42%，开盘买在高位）。
    10:00 后不再过滤（正常买入，仍有大跌市 -3% 保护）。
    返回 True = 开盘方向弱，缓买"""
    now_ts = datetime.now().strftime('%H:%M:%S')
    if now_ts >= OPEN_WEAK_UNTIL:
        return False
    if market_ret is None:
        market_ret = market_ret_realtime()
    return market_ret <= OPEN_WEAK_THRESHOLD


def is_downtrend(tushare, trade_date):
    """下跌趋势判定（2026-08-19 维度2，用户拍板）：近 TREND_DROP_DAYS 交易日累计跌幅
    ≤ TREND_DROP_THRESHOLD(-4%) → 视为下跌趋势（慢熊保护：单日未到 -1.5%/-3% 阈值但
    连跌数日的"温水煮青蛙"，防止满仓被套——8/19 暴跌前夜正是连跌形态）。
    用 index_daily_raw 中证1000 收盘价（含当日最新收盘；盘中 daily 无当日时用最近交易日，
    慢熊是日线级别判断，不依赖盘中实时）。
    返回 (是否下跌趋势, 累计跌幅%)"""
    try:
        rows = tushare.execute(
            "SELECT trade_date, close FROM index_daily_raw "
            "WHERE ts_code='000852.SH' AND trade_date <= ? "
            "ORDER BY trade_date DESC LIMIT ?",
            (str(trade_date), TREND_DROP_DAYS + 1)).fetchall()
        # rows: [[最新日, close], [前1日, close], ..., [前N日, close]]
        if len(rows) < 2:
            return False, 0.0
        latest = float(rows[0][1])
        base_idx = min(len(rows) - 1, TREND_DROP_DAYS)
        base = float(rows[base_idx][1])
        if latest <= 0 or base <= 0:
            return False, 0.0
        cum_ret = (latest / base - 1) * 100
        return cum_ret <= TREND_DROP_THRESHOLD, cum_ret
    except Exception:
        return False, 0.0


def _log_trade(state, aid, code, name, direction, price, shares, amount, signal_score=None, trade_time=None, reason=None, pnl=None):
    """策略账户成交写 ledger.db.trade_log（供面板「交易流水」tab 展示，strategy=账户id）"""
    try:
        ts = trade_time or datetime.now().strftime('%H:%M:%S')
        # 2026-08-24 修复：显式指定全局唯一 id（原不指定 → NULL；面板按 id 排序错乱）
        max_id = state.execute("SELECT MAX(id) FROM trade_log").fetchone()[0] or 0
        state.execute("""
            INSERT INTO trade_log
            (id, code, name, direction, price, quantity, amount, trade_date, trade_time,
             strategy, signal_score, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (max_id + 1, code, name, direction, round(float(price), 4), int(shares),
              round(float(amount), 4),
              datetime.now().strftime('%Y-%m-%d'), ts,
              aid, signal_score, ('策略模拟账户|' + reason) if reason else '策略模拟账户'))
        # 2026-08-28 修复：必须立即 commit——否则主连接挂起写事务（RESERVED 锁），
        # 随后 AccountStore.save() 的新连接写 ledger.db 会被同进程双连接互锁
        # （database is locked，每账户等 30s busy_timeout → 连锁失败 → 部分账户停更）
        # 迁移前 save 写 JSON 不碰 DB，此漏 commit 无感知；DB-first 后必须提交。
        state.commit()
        # QQ 实时推送成交（异步不阻塞，失败静默；2026-08-03）
        try:
            from pathlib import Path
            base = Path(__file__).resolve().parent.parent
            acct_name = ACCOUNTS.get(aid, {}).get('name', aid)
            subprocess.Popen(
                [sys.executable, '-B', str(base / 'scripts' / 'notify_trade.py'),
                 acct_name, direction, code, name or code, str(int(shares)),
                 str(round(float(price), 2)), str(round(float(amount), 2)),
                 str(reason or ''),
                 str(pnl or '')],  # 2026-09-14: 推送带上触发条件+卖出盈亏
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    except Exception as e:
        print(f"  ⚠️ trade_log 写入失败: {e}")


def get_signal_score(state, src, code, d):
    """按 src 查信号日 d 该票的信号分（止损卖出时记录用；MacBook v2 信号表在 sig. 前缀）"""
    try:
        if src == 'fusion_3f':
            r = state.execute("SELECT fusion_3f_score FROM sig.fusion_3f_signals WHERE REPLACE(date,'-','')=? AND stock_code=?", (d, code)).fetchone()
        elif src == 'cmmr':
            r = state.execute("SELECT cmmr_score FROM sig.signal_history WHERE REPLACE(date,'-','')=? AND stock_code=?", (d, code)).fetchone()
        elif src == 'cmmr_clf':  # 验证账户：信号分记母池 cmmr_score（门票分另见面板选池）
            r = state.execute("SELECT cmmr_score FROM sig.signal_history WHERE REPLACE(date,'-','')=? AND stock_code=?", (d, code)).fetchone()
        elif src == 'cmmr_fusion':
            r = state.execute("SELECT fusion_score_cmmr FROM sig.signal_history WHERE REPLACE(date,'-','')=? AND stock_code=?", (d, code)).fetchone()
        elif src == 'fusion_center':
            r = state.execute("SELECT score FROM sig.fusion_center_signals WHERE REPLACE(date,'-','')=? AND stock_code=?", (d, code)).fetchone()
        else:
            r = None
        return float(r[0]) if r and r[0] is not None else None
    except Exception:
        return None

def _pos_expired(tushare, trade_date, buy_date, last_re, rebalance_n):
    """持仓信号是否已到期（重评日重建只清到期仓，2026-09-02 用户拍板）。
    - 有 last_re：买入日 ≤ 上次重评日 = 上次重建的旧仓（已满窗口）→ 到期；
      买入日晚于 last_re = 窗口期内 top-up 补仓（信号未过期，重评日不清，
      9/1 刚买的荣信文化次日被无脑清仓 -6.6% 案例）。
    - 无 last_re（v1 迁移兜底）：按买入日起交易日数 ≥ 窗口判定（与 is_re 同口径）。
    返回 True = 到期（可清），False = 信号未过期（保留）。"""
    b = str(buy_date or '').replace('-', '')
    if not b:
        return False
    if last_re:
        return b <= str(last_re).replace('-', '')
    try:
        n = tushare.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?",
            (b,)).fetchone()[0]
        latest_daily = tushare.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
        if latest_daily and str(latest_daily) < str(trade_date):
            n = int(n or 0) + 1
        return int(n or 0) >= rebalance_n
    except Exception:
        return True  # 查不到按到期处理（保守）



def topup_gap(acct, targets, rtp, prev_map, state, tushare, aid, trade_date, now_ts, name_map):
    """非重评日只补「已持有目标仓」的等权缺口（topup='gap' 生产口径，2026-09-11 用户拍板）。

    与旧口径（topup='all'）的唯一差别：不买未持有的目标票——新票只在重评日纳入，窗口内
    卖出释放的现金留存到下次重评。目的：组合严格 = 重评日 top10 等权（与 17 年回测口径一致），
    不再被每日名单漂移摊成几十个 1% 碎仓（M2 审计：fusion_center 47 只/20 只<1%）。
    其余约束与重评日补差一致：per_target=(现金+保留目标仓市值)/目标数、R2 不追高 7%、
    冷却三腿、止盈禁买回、R7 观察窗（浮亏≤-6% 不加仓）、MIN_BUY_AMOUNT、100/200 股规则。
    """
    n_tgt = len(targets)
    if not n_tgt:
        return
    held = {p.code: p for p in acct.positions}
    held_val = sum(held[c].shares * (rtp.get(c) or held[c].avg_cost) for c, _ in targets if c in held)
    per_target = (acct.cash + held_val) / n_tgt * defense.buy_scale(DMODE)
    # 2026-09-21 防碎门槛（用户拍板）：per_target 仍按原口径（= 可用资源内的等权目标），
    #   只新增一道「最小建仓权重」闸门 = max(2000, NAV×2.5%)。理由：原门槛固定 2000 元
    #   = 0.18% NAV 等于不设防，会补出 <1% 的碎仓；低于门槛时本账户本次不补（宁可留现金）。
    #   ⚠️ 不要把 per_target 本身改成 NAV/n_tgt —— 那会无视「掉榜未到期持仓占用的资金」，
    #   目标虚高 → 补不满 → 偏离等权（单测 test_overlap_rebuilt_without_churn 实测偏离 5.8%）。
    nav = acct.cash + sum(p.shares * (rtp.get(p.code) or p.avg_cost) for p in acct.positions)
    min_buy = max(MIN_BUY_AMOUNT, nav * MIN_POSITION_RATIO)
    if per_target < min_buy:
        return
    deficits = []
    for code, score in targets:
        pos = held.get(code)
        px = rtp.get(code)
        if pos is None or not px or px <= 0:
            continue  # ★ 未持有 → 不买（这正是与旧口径的差别）
        if prev_map.get(code) and prev_map[code] > 0 and px / prev_map[code] - 1 >= 0.07:
            print(f"  ⏭ {code} 较昨收≥7% R2不追高，不加仓")
            continue
        _blk, _why = cooldown.check_cooldown(state, code, aid, px, score)
        if _blk:
            print(f"  🧊 {code} 冷却拦截: {_why}（持有则保留不加仓）")
            continue
        _tblk, _twhy = cooldown.check_tp_ban(state, tushare, code, aid, trade_date, TP_REENTRY_BAN_DAYS)
        if _tblk:
            print(f"  🛡️ {code} {_twhy}（禁买期内不加回）")
            continue
        if px <= pos.avg_cost * defense.float_stop(DMODE):
            print(f"  ⏭ {code} 浮亏≤-{(1-defense.float_stop(DMODE))*100:.0f}% R7观察窗，不加仓（等尾盘裁决）")
            continue
        need = per_target - pos.shares * px
        if need >= min_buy:
            deficits.append((need, code, score, pos, px))
    if not deficits or acct.cash < min_buy:
        return
    print(f"  ⚖️ {aid} 窗口内补缺口: per_target={per_target:,.0f}（只补已持有目标仓，不买新票）")
    for need, code, score, pos, px in sorted(deficits, key=lambda x: -x[0]):
        budget = min(need, acct.cash)
        if budget < min_buy:
            break
        shares = int(budget / px / 100) * 100
        if shares < 100:
            continue
        if (code.startswith('30') or code.startswith('68')) and shares < 200:
            print(f"  ⏭ {code} 科创/创业板 <200股最低申报，跳过")
            continue
        cost = shares * px
        if cost > acct.cash:
            shares = int(acct.cash / px / 100) * 100
            cost = shares * px
            if (code.startswith('30') or code.startswith('68')) and shares < 200:
                continue
            if shares < 100:
                continue
        acct.cash -= cost
        acct.add_position(Position(
            code=code, name=pos.name, shares=shares, avg_cost=round(px, 3),
            buy_date=trade_date, peak_price=round(px, 3),
            stop_loss=round(px * 0.88, 2), target=0))
        acct.trades.append(Trade(
            date=trade_date, action='买入', code=code, name=pos.name,
            price=round(px, 3), shares=shares, amount=round(cost, 2),
            signal_score=score, reason='窗口内补缺口', trade_time=now_ts))
        _log_trade(state, aid, code, pos.name, 'BUY', px, shares, cost, score, now_ts, reason='窗口内补缺口')
        print(f"  📈 补缺口 {code} {shares}股 @{px:.2f} → 现共{pos.shares}股 "
              f"(等权目标{per_target:,.0f}) 评分{score:.3f}")


def run_day(store, state, tushare, d, trade_date, aid, bad_codes, mkt_ret):
    """盘中实时价调仓：用最近信号日 d 的信号，按 Sina 实时价成交，NAV 实时价估值。
    2026-09-01 冷却机制：止损出清进冷却（时间/价格/模型三腿），重评日清时间腿。"""
    cooldown.ensure_table(state)  # 冷却表（2026-09-01，建在 ledger.db 主库）
    cooldown.ensure_tp_ban_table(state)  # 止盈禁买表（2026-09-02）
    """盘中实时价调仓：用最近信号日 d 的信号，按 Sina 实时价成交，NAV 实时价估值。
    trade_date = 今天(成交日)。停牌/无实时价的标的跳过（不买不卖）。"""
    src = ACCOUNTS[aid]['src']
    acct = store.load(aid)
    # manual 账户（agent_auto）：本脚本只 NAV 估值，绝不动持仓（交易归 agent_trade_decision.py）
    if ACCOUNTS[aid].get('manual'):
        all_c = list(dict.fromkeys([p.code for p in acct.positions]))
        rtp_m = fetch_prices_batch(all_c) if all_c else {}
        pos_val = sum(p.shares * (rtp_m.get(p.code) or p.avg_cost) for p in acct.positions)
        nav = acct.cash + pos_val
        prev_hist = [h for h in acct.nav_history if str(h.get('date', '')).replace('-', '') != str(trade_date)]
        prev = prev_hist[-1].get('nav') if prev_hist else acct.initial_capital
        daily_ret = round((nav / prev - 1) * 100, 4) if prev > 0 else 0.0
        if abs(daily_ret) > 30:
            print(f"  ⚠️ {aid} daily_ret={daily_ret:.2f}% 异常，NAV 不落库")
            return acct, nav, None
        acct.record_nav(rtp_m)
        store.save(acct)
        state.execute("""
            INSERT OR REPLACE INTO strategy_accounts
            (account_id, date, nav, cash, pos_value, daily_ret, market_ret, n_pos)
            VALUES (?,?,?,?,?,?,?,?)
        """, (aid, trade_date, round(nav, 2), round(acct.cash, 2), round(pos_val, 2),
              daily_ret, mkt_ret, len(acct.positions)))
        state.commit()
        print(f"  [manual] 只估值: NAV={nav:,.0f} ({daily_ret:+.2f}%) 持仓{len(acct.positions)}只")
        return acct, nav, daily_ret
    # 重评日判定（2026-08-03 信号-执行匹配）：窗口长度按账户取 ACCOUNTS[aid]['rebalance']——
    # 中枢版 2026-09-11 起 20 日（原 10）、中枢+三模型 20 日、双信号组合 15 日、其余默认 10 日。
    # 窗口期内只跑止损/止盈，不做排名换仓（信号是窗口期预测，每天换仓=信号频率错配）
    last_re = str(acct.config.get('last_rebalance_date') or '').replace('-', '')
    rebalance_n = ACCOUNTS[aid].get('rebalance', REBALANCE_INTERVAL)  # per-account 重评窗口（2026-08-10）
    is_re = True
    if last_re:
        try:
            # 2026-08-18 修复：盘中 daily 无当天数据 → 重评日永远晚 1 天触发（8/4 建仓 + 10 交易日
            # = 8/18 到期，但盘中 daily 到 8/17，计数 9 < 10 → 误判非重评日，从未调仓）。
            # 修正：数 daily 中 last_re 之后的所有交易日（不含 last_re），若最新交易日 < 今天
            # 且今天在交易时段（main 已用 Sina 指数实时波动判断过），则今天算第 N+1 个交易日。
            n = tushare.execute(
                "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?",
                (last_re,)).fetchone()[0]
            latest_daily = tushare.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
            if latest_daily and str(latest_daily) < str(trade_date):
                n = int(n or 0) + 1  # 今天交易日，盘中 daily 未收录 → 补 1
            is_re = int(n or 0) >= rebalance_n
        except Exception:
            is_re = True
    else:
        # 2026-08-04 B方案防御：last_re 缺失但有持仓（v1→v2 迁移遗留，8/3 建仓未写 last_re
        # 导致 8/4 被误判重评日全仓换股）→ 用最早建仓日兜底判定，窗口未满不重评
        if acct.positions:
            try:
                earliest = min(str(p.buy_date).replace('-', '') for p in acct.positions)
                n = tushare.execute(
                    "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?",
                    (earliest,)).fetchone()[0]
                latest_daily = tushare.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
                if latest_daily and str(latest_daily) < str(trade_date):
                    n = int(n or 0) + 1
                is_re = int(n or 0) >= rebalance_n
            except Exception:
                is_re = False  # 兜底日未知，保守不重评
    # 目标持仓：top10 买入（严格，重评日整仓重建基准）
    targets = get_signal_targets(state, tushare, d, src, bad_codes)
    target_codes = {c for c, _ in targets}
    # 股票名称（写入账户 JSON，供前端展示）
    name_map = {}
    try:
        for c in target_codes:
            _r = tushare.execute(
                "SELECT name FROM stock_basic WHERE ts_code=?", (ts_code(c),)).fetchone()
            if _r and _r[0]:
                name_map[c] = _r[0]
    except Exception:
        pass
    # ── 实时价（目标 + 持仓 一次批量拉取）──
    all_codes = [c for c, _ in targets] + [p.code for p in acct.positions]
    all_codes = list(dict.fromkeys(all_codes))
    rtp = fetch_prices_batch(all_codes)  # {code: 实时价}
    if not rtp:
        print(f"  ⚠️ 实时价全部获取失败，跳过 {aid}（可能非交易时段/节假日）")
        return None
    # ── 卖出：R5 硬止损 / R6 移动止盈 / R7 浮亏止损 随时触发；重评日整仓重建（B方案 2026-08-04）──
    # B方案（用户 2026-08-04）：去掉 R4 跌出top20 排名卖出——信号日间 top20 交集仅 0~3/20，
    # 排名边界在信号漂移面前=重评日必然清仓。改为：窗口期内只靠 R5/R6 风控保护；
    # 重评日（该账户 rebalance 窗口到期）整仓重建：旧信号过期，全部卖出 → 按新信号 top10 重新等权建仓。
    # T+1 制度：当日买入的持仓不可当日卖出（buy_date == trade_date 跳过，2026-08-03 用户要求）
    now_ts = datetime.now().strftime('%H:%M:%S')
    # 2026-09-01 冷却机制：重评日清空时间腿（cooldown→memory，价格/模型腿继续长期有效）。
    # ⚠️ 2026-09-02：清腿必须在卖出段之前执行——重评日当天新产生的止损冷却保留时间腿到
    #    下次重评，防"早盘止损 → 同日清腿 → 同 tick 买回"绕过冷却（原位置在卖出段后）。
    if is_re:
        cooldown.clear_time_legs(state, aid)
    # 2026-09-02 重评日重建语义（用户拍板：废除无脑清仓——9/1 刚 top-up 的信号 9/2 就被
    # 当"旧信号过期"清掉，1 天亏 4~7% 落袋）：
    #   1) 风控红线优先（重评日同样生效）：硬止损/加速止损/浮亏止损/回撤止盈照卖，进冷却；
    #   2) 到期判定：买入日 ≤ 上次重评日 = 满窗口旧仓 → 不在新 top10 则"窗口到期重建"卖出；
    #      仍在 top10 → 保留（买入段补差到等权，不再卖旧开新空转）；
    #   3) 买入日晚于上次重评日 = 窗口期内 top-up 仓，信号未过期 → 无论是否在新 top10 都保留。
    last_re_norm = str(acct.config.get('last_rebalance_date') or '').replace('-', '') or None
    # 重评日碎仓清理用的实时 NAV（2026-09-11）：权重阈值 = NAV × DUST_CLEAN_RATIO
    nav_at_sell = acct.cash + sum(x.shares * (rtp.get(x.code) or x.avg_cost) for x in acct.positions)
    # crash2 减仓清单（2026-09-16 挂上，每账户独立算）：市值按 fusion 升序整仓卖到 ≤ NAV×50%
    crash2_cut = set()
    if DMODE == 'crash2' and acct.positions and nav_at_sell > 0:
        _fuse = {}
        for p in acct.positions:
            _fr = get_signal_score(state, src, p.code, d)  # 信号日分（fusion_center 即 fusion 分）
            _fuse[p.code] = _fr if _fr is not None else 999.0
        _mv = {p.code: p.shares * (rtp.get(p.code) or p.avg_cost) for p in acct.positions}
        _sell_mv = acct.cash + sum(_mv.values()) - nav_at_sell * defense.CRASH2_KEEP
        for _c in sorted(_mv, key=lambda c: _fuse[c]):
            if _sell_mv <= 0:
                break
            crash2_cut.add(_c)
            _sell_mv -= _mv[_c]
        if crash2_cut:
            print(f"  🛡️ crash2 减仓清单: {sorted(crash2_cut)}（fusion升序，减至5成仓）")
    _float_floor = defense.float_stop(DMODE)  # 防御态 R7 地板（halved/crash2 → -5%）
    for p in list(acct.positions):
        if str(p.buy_date).replace('-', '') == str(trade_date):
            print(f"  ⏭ {p.code} 今日买入(T+1)，不可当日卖出，保留")
            continue
        px = rtp.get(p.code)
        if not px or px <= 0:
            print(f"  ⏭ {p.code} 无实时价(停牌?)，保留")
            continue
        # 峰值跟踪（移动止盈用）：peak = max(peak, 现价)
        if px > p.peak_price:
            p.peak_price = round(px, 3)
        # 执行规则（2026-08-04 B方案 + 2026-08-29 增补 R7 + 2026-08-31 三档化 + 2026-09-02 重建语义）：
        #   R5 硬止损：现价 ≤ 成本×0.88 → 卖（无条件，任何时间，重评日也生效）
        #   加速止损：现价 ≤ 成本×0.91 → 卖（无条件，2026-08-31 新增：从 -6% 继续跌到 -9%
        #     = 恶化确认非假摔，立即离场，不等到 -12%）
        #   R7 浮亏止损（2026-08-29 用户批准新增）：现价 ≤ 成本×0.94 → 尾盘确认卖
        #     回测（8月43笔亏损单，_backtest_r7_stop.py）：-6%阈值砍14笔，
        #     亏损单金额加权均亏 -3.9 -> -3.6pp；61笔盈利单 0 误杀（-4%/-5%仅1笔）。
        #     动机：策略账户原左尾全压到 -12% 硬止损，8月均亏-7.9%（主账户-1.9%）。
        #     2026-08-31 尾盘确认：开盘破位（开盘价已在止损线下=隔夜利空）立即卖；
        #     平开/高开后盘中跌破 → 14:30 后确认卖（8/31 统计 13 笔止损 77% 当日反弹，
        #     早盘急跌多为假摔，尾盘确认躲洗盘；14:30 前只监控不卖）
        #   R6 移动止盈：峰值≥成本×1.05 且 现价≤峰值×0.92 → 卖（随时，回撤8%落袋）
        #   ⚠️ 2026-08-31 修复延续：风控分支不设 elif 卡链（浮亏止损早盘未破位时 reason 留 None，
        #     不阻止后续到期重建判定）；重建判定独立 if，重评日不再跳过风控。
        reason = None
        if px <= p.avg_cost * HARD_STOP_FLOOR:
            reason = '硬止损-12%'
        elif px <= p.avg_cost * ACCEL_STOP_FLOOR:
            reason = '加速止损-9%'
        elif px <= p.avg_cost * _float_floor:
            # 尾盘确认：拿开盘价判断是否隔夜破位（拿不到开盘价按盘中跌破处理=尾盘确认，保守不误杀）
            try:
                open_px = fetch_price_open(p.code)
            except Exception:
                open_px = None
            if open_px is not None and open_px > 0 and open_px <= p.avg_cost * _float_floor:
                reason = f'浮亏止损-{(1-_float_floor)*100:.0f}%(开盘破位)'
            elif now_ts[:5] >= STOP_CONFIRM_TIME:
                reason = f'浮亏止损-{(1-_float_floor)*100:.0f}%'
        elif p.peak_price >= p.avg_cost * 1.05 and px <= p.peak_price * 0.92:
            # 2026-09-02 用户拍板：止盈=安全规则，不因"在 top10 名单/重评日续持"豁免——
            # 触发止盈/止损的票一律卖出且禁买回（止盈禁买记 trade_tp_ban，见卖出段）
            reason = '回撤止盈'
        # 2026-09-16 防御规则 5D（用户拍板"挂上"，core/defense.py）：
        #   crash2 减仓清单（fusion 升序整仓卖到市值≤50%）→ 优先于一切保留逻辑；
        #   halved/crash2 且最新 fusion<3 → 清出（砍模型最不看好的，不是砍亏最多的）。
        #   主账户 T+1/停牌分支已在上方 continue，这里天然继承；None 不误杀。
        if reason is None and DMODE != 'normal':
            _dfuse = None
            try:
                _drow = state.execute(
                    "SELECT fusion_score FROM sig.signal_history "
                    "WHERE date = (SELECT MAX(date) FROM sig.signal_history) "
                    "AND stock_code = ?", (p.code,)).fetchone()
                _dfuse = float(_drow[0]) if _drow and _drow[0] is not None else None
            except Exception:
                pass
            if p.code in crash2_cut:
                reason = f'防御减仓({DMODE}·5成仓)'
            elif _dfuse is not None and _dfuse < 3:
                reason = f'防御清票(fusion{_dfuse:.1f}<3·{DMODE})'
        # 重评日窗口到期重建：只清"满窗口且已不在新 top10"的旧仓
        if reason is None and is_re:
            expired = _pos_expired(tushare, trade_date, p.buy_date, last_re_norm, rebalance_n)
            if expired and p.code not in target_codes:
                reason = '窗口到期重建'
            elif expired and p.code in target_codes:
                print(f"  ♻️ {p.code} 窗口到期但仍在 top10 → 保留，买入段补差到等权")
            else:
                print(f"  ♻️ {p.code} 信号未到期 → 保留（重评日不清刚买的仓）")
        # 2026-09-11 新增：重评日碎仓清理——权重 < NAV×DUST_CLEAN_RATIO(1%) 且不在新 top10 的
        # 残留小仓一并卖出（原规则只清"满窗口"仓 → 窗口期内摊出的碎仓最长滞留 2 个窗口）
        if reason is None and is_re and p.code not in target_codes and nav_at_sell > 0 \
                and p.shares * px < nav_at_sell * DUST_CLEAN_RATIO:
            reason = '碎仓清理'
            print(f"  🧹 {p.code} 碎仓清理（权重{p.shares * px / nav_at_sell * 100:.2f}%<1%，不在新 top10）")
        if reason is None:
            continue
        amount = p.shares * px
        acct.cash += amount
        acct.trades.append(Trade(
            date=trade_date, action='卖出', code=p.code, name=p.name,
            price=round(px, 3), shares=p.shares, amount=round(amount, 2),
            pnl_pct=round((px / p.avg_cost - 1) * 100, 2) if p.avg_cost else None,
            reason=reason, trade_time=now_ts))
        _pnl_yuan = p.shares * (px - p.avg_cost) if p.avg_cost else 0.0
        _pnl_pct = (px / p.avg_cost - 1) * 100 if p.avg_cost else 0.0
        _log_trade(state, aid, p.code, p.name, 'SELL', px, p.shares, amount, None, now_ts,
                   reason=reason, pnl=f"{_pnl_yuan:+,.0f}元 ({_pnl_pct:+.2f}%)")
        acct.remove_position(p.code)
        # 2026-09-01 冷却机制：止损类卖出（持仓清零）→ 写冷却+止损记忆
        # （止盈/重建/部分减仓不进；二次止损 UPSERT 覆盖）
        if cooldown.is_stop_reason(reason):
            _sell_score = dict(targets).get(p.code) or get_signal_score(state, src, p.code, d)
            cooldown.add_stop_memory(state, p.code, aid, round(px, 3), _sell_score, str(trade_date))
            print(f"  🧊 {p.code} 止损出清 → 进冷却（sell@{px:.2f} score={_sell_score}）")
        elif reason == '回撤止盈':
            # 2026-09-02 止盈卖出 → 短期禁买回（trade_tp_ban，与名单无关；时长 TP_REENTRY_BAN_DAYS）
            cooldown.add_tp_ban(state, p.code, aid, str(trade_date))
            print(f"  🛡️ {p.code} 回撤止盈 → 禁买回{TP_REENTRY_BAN_DAYS}交易日")
        print(f"  💸 卖 {p.code} {p.shares}股 @{px:.2f} ({reason})")
    # ── 买入 ──
    #   非重评日：每交易日补目标缺口（2026-08-18 改造：不再等重评日才买；原逻辑不变）
    #   重评日（2026-09-02 用户拍板，废除"整仓全卖→再全买"无脑清仓）：
    #     卖出段只清了"满窗口且不在新 top10"的旧仓；此处 per_target = (现金 + 保留目标仓市值)/目标数，
    #     已持有的目标票只补差到等权、缺失票全额建仓——新旧 top10 重叠不再同 tick 先卖后买空转
    #     （9/2 实盘 cmmr_fusion 003001 卖3800买10000 等 8 对案例）
    #   大跌市（尾盘确认 ≤-3% 或次日未收复）停买保留现金。优先级 crash > 趋势 > open_weak。
    crash, crash_reason = is_crash_market(state, trade_date, mkt_ret)
    if crash:
        print(f"  🛑 {aid} 大跌市停买: {crash_reason}")
    elif is_open_weak(mkt_ret):
        print(f"  ⏳ {aid} 开盘方向弱(中证1000 {mkt_ret:+.2f}%≤{OPEN_WEAK_THRESHOLD}%)，观察期缓买")
    else:
        # 下跌趋势（维度2，2026-08-19）：近3日累计跌幅 ≤-4% → 本轮跳过买入（缓买）
        #   慢熊保护：单日未到 -1.5%/-3% 阈值但连跌数日（温水煮青蛙）→ 不买，
        #   等趋势修复（3日累计回到 -4% 以上）再恢复。优先级 crash > 趋势 > open_weak
        downtrend, cum_ret = is_downtrend(tushare, trade_date)
        # ⚠️ 2026-08-24 修复：prev_map 提前初始化（原代码只在非下跌分支定义，
        # 下跌趋势且存在买入缺口时引用未定义变量 → UnboundLocalError → run_day 中断，
        # NAV 不写 + store.save 不执行（持仓 JSON 不更新，trade_log 重复卖出累积））
        prev_map = {}
        if downtrend:
            print(f"  ⏳ {aid} 近{TREND_DROP_DAYS}日累计{cum_ret:+.2f}%≤{TREND_DROP_THRESHOLD}%（下跌趋势），本轮缓买")
        else:
            # 昨收（tushare daily 最新交易日 close，用于 R2 不追高判断）
            try:
                for r in tushare.execute(
                    "SELECT ts_code, close FROM daily WHERE trade_date = (SELECT MAX(trade_date) FROM daily)"
                ).fetchall():
                    prev_map[r[0].split('.')[0]] = float(r[1])
            except Exception:
                pass
            if is_re:
                # ── 重评日：等权整仓补差（2026-09-02 用户拍板）──
                held = {p.code: p for p in acct.positions}
                n_tgt = len(target_codes)
                held_val = sum(held[c].shares * rtp[c]
                               for c, _ in targets if c in held and rtp.get(c))
                per_target = ((acct.cash + held_val) / n_tgt if n_tgt else 0.0) * defense.buy_scale(DMODE)
                # 2026-09-21 防碎门槛（per_target 语义不变，只加闸门；详见 topup_gap 注释）
                nav = acct.cash + sum(p.shares * (rtp.get(p.code) or p.avg_cost) for p in acct.positions)
                min_buy = max(MIN_BUY_AMOUNT, nav * MIN_POSITION_RATIO)
                if n_tgt == 0 or per_target < min_buy:
                    print(f"  ⏭ {aid} 重评日无目标或预算不足(per_target={per_target:,.0f})，不买")
                else:
                    print(f"  ⚖️ {aid} 重评等权: per_target={per_target:,.0f} "
                          f"(现金{acct.cash:,.0f}+保留目标仓{held_val:,.0f}) / {n_tgt}")
                    for code, score in targets:
                        px = rtp.get(code)
                        if not px or px <= 0:
                            print(f"  ⏭ {code} 无实时价(停牌?)，跳过")
                            continue
                        pos = held.get(code)
                        # R2 不追高：实时价较昨收涨幅 ≥ 7% 当日跳过（新买/补差一致，避免追涨停）
                        if prev_map.get(code) and prev_map[code] > 0 \
                                and px / prev_map[code] - 1 >= 0.07:
                            print(f"  ⏭ {code} 较昨收≥7% R2不追高，跳过")
                            continue
                        # 冷却三腿（全局版 2026-09-01）：补差买入同样受约束
                        # （600363 型跨账户记录照拦；自家今日止损记录=时间腿仍在，拦同日买回）
                        _blk, _why = cooldown.check_cooldown(state, code, aid, px, score)
                        if _blk:
                            print(f"  🧊 {code} 冷却拦截: {_why}（持有则保留不加仓）")
                            continue
                        # 2026-09-02 止盈禁买回（与名单无关）：触发过回撤止盈的票禁买期内不接回
                        _tblk, _twhy = cooldown.check_tp_ban(state, tushare, code, aid, trade_date, TP_REENTRY_BAN_DAYS)
                        if _tblk:
                            print(f"  🛡️ {code} {_twhy}（禁买期内不加回）")
                            continue
                        have_val = pos.shares * px if pos else 0.0
                        # R7 观察窗：已持有且现价 ≤ 成本×0.94 → 不加仓（14:30 由卖出段裁决止损；
                        # 防"早盘补差加仓 → 14:30 浮亏止损全卖"的亏损放大）
                        if pos and px <= pos.avg_cost * defense.float_stop(DMODE):
                            print(f"  ⏭ {code} 浮亏≤-{(1-defense.float_stop(DMODE))*100:.0f}% R7观察窗，不加仓（等尾盘裁决）")
                            continue
                        need = per_target - have_val
                        if need < min_buy:
                            if pos:
                                print(f"  ⏭ {code} 已有市值{have_val:,.0f}≈等权{per_target:,.0f}，无需补")
                            else:
                                print(f"  ⏭ {code} 预算{per_target:,.0f}<2000 最小买入，跳过")
                            continue
                        shares = int(need / px / 100) * 100
                        if shares < 100:
                            continue
                        # 2026-08-31 硬校验：科创(68)/创业(30) 板最低申报 200 股
                        if (code.startswith('30') or code.startswith('68')) and shares < 200:
                            print(f"  ⏭ {code} 科创/创业板 <200股最低申报，跳过")
                            continue
                        cost = shares * px
                        if cost > acct.cash:
                            shares = int(acct.cash / px / 100) * 100
                            cost = shares * px
                            if (code.startswith('30') or code.startswith('68')) and shares < 200:
                                continue
                            if shares < 100:
                                continue
                        if cost <= 0:
                            continue
                        acct.cash -= cost
                        if pos:
                            # 补差：并入原仓（add_position 加权平均成本，buy_date/peak 保留）
                            acct.add_position(Position(
                                code=code, name=pos.name, shares=shares, avg_cost=round(px, 3),
                                buy_date=trade_date, peak_price=round(px, 3),
                                stop_loss=round(px * 0.88, 2), target=0))
                            acct.trades.append(Trade(
                                date=trade_date, action='买入', code=code, name=pos.name,
                                price=round(px, 3), shares=shares, amount=round(cost, 2),
                                signal_score=score, reason='重评补差至等权', trade_time=now_ts))
                            _log_trade(state, aid, code, pos.name, 'BUY', px, shares, cost, score, now_ts, reason='重评补差至等权')
                            print(f"  📈 补差 {code} {shares}股 @{px:.2f} → 现共{pos.shares}股 "
                                  f"(等权目标{per_target:,.0f}) 评分{score:.3f}")
                        else:
                            acct.add_position(Position(
                                code=code, name=name_map.get(code, ''), shares=shares, avg_cost=round(px, 3),
                                buy_date=trade_date, peak_price=round(px, 3),
                                stop_loss=round(px * 0.88, 2), target=0))
                            acct.trades.append(Trade(
                                date=trade_date, action='买入', code=code, name=name_map.get(code, ''),
                                price=round(px, 3), shares=shares, amount=round(cost, 2),
                                signal_score=score, reason='重评等权建仓', trade_time=now_ts))
                            _log_trade(state, aid, code, name_map.get(code, ''), 'BUY', px, shares, cost, score, now_ts, reason='重评等权建仓')
                            print(f"  📈 建仓 {code} {shares}股 @{px:.2f} (实时价) 评分{score:.3f}")
            else:
                # ── 非重评日：每日补目标缺口（2026-08-18 改造；2026-09-11 起 topup='gap'）──
                # gap：只补"已持有目标仓"的等权缺口，不买新票（新票只在重评日纳入）
                if ACCOUNTS[aid].get('topup', 'gap') == 'gap':
                    topup_gap(acct, targets, rtp, prev_map, state, tushare, aid, trade_date, now_ts, name_map)
                    missing = []
                else:
                    missing = [c for c, _ in targets if c not in {p.code for p in acct.positions}]
                missing = [c for c in missing if rtp.get(c) and rtp[c] > 0]
                # R2 不追高：实时价较昨收涨幅 ≥ 7% 当日跳过（等回调，避免追涨停）
                missing = [c for c in missing
                           if not (prev_map.get(c) and prev_map[c] > 0
                                   and rtp[c] / prev_map[c] - 1 >= 0.07)]
                # 2026-09-01 冷却机制：买入候选过滤（时间腿/价格腿/模型腿，全过才放行）
                _score_map = dict(targets)
                _cd_ok = []
                for c in missing:
                    _blk, _why = cooldown.check_cooldown(state, c, aid, rtp.get(c, 0), _score_map.get(c))
                    if _blk:
                        print(f"  🧊 {c} 冷却拦截: {_why}")
                        continue
                    # 2026-09-02 止盈禁买回（与名单无关）：止盈卖出当日/禁买期内不接回
                    _tblk, _twhy = cooldown.check_tp_ban(state, tushare, c, aid, trade_date, TP_REENTRY_BAN_DAYS)
                    if _tblk:
                        print(f"  🛡️ {c} {_twhy}（当日禁买回）")
                        continue
                    _cd_ok.append(c)
                missing = _cd_ok
                if missing and acct.cash >= MIN_BUY_AMOUNT:
                    # 2026-08-28 聚合门槛：不摊零钱（碎仓根源），现金能满额买几只买几只
                    n_buy = min(len(missing), max(1, int(acct.cash // MIN_BUY_AMOUNT)))
                    per = acct.cash / n_buy * defense.buy_scale(DMODE)
                    bought = 0
                    for code, score in targets:
                        if code not in missing:
                            continue
                        if bought >= n_buy:
                            break
                        px = rtp[code]
                        shares = int(per / px / 100) * 100
                        if shares < 100:
                            continue
                        # 2026-08-31 硬校验：科创(68)/创业(30) 板最低申报 200 股，<200 直接跳过
                        # （原 MIN_BUY_AMOUNT=2000 只拦金额不拦数量，全库 24 笔 100 股买单=真实世界废单）
                        if (code.startswith('30') or code.startswith('68')) and shares < 200:
                            print(f"  ⏭ {code} 科创/创业板 100股<200 最低申报，跳过")
                            continue
                        cost = shares * px
                        if cost > acct.cash:
                            shares = int(acct.cash / px / 100) * 100
                            cost = shares * px
                        # 二次调低后同样过 200 股门槛（30/688），否则现金不足时会调回 100 股漏过
                        if (code.startswith('30') or code.startswith('68')) and shares < 200:
                            continue
                        if shares < 100:
                            continue
                        acct.cash -= cost
                        bought += 1
                        acct.trades.append(Trade(
                            date=trade_date, action='买入', code=code, name=name_map.get(code, ''),
                            price=round(px, 3), shares=shares, amount=round(cost, 2),
                            signal_score=score, reason='信号top10买入', trade_time=now_ts))
                        _log_trade(state, aid, code, name_map.get(code, ''), 'BUY', px, shares, cost, score, now_ts, reason='信号top10买入')
                        acct.add_position(Position(
                            code=code, name=name_map.get(code, ''), shares=shares, avg_cost=round(px, 3),
                            buy_date=trade_date, peak_price=round(px, 3),
                            stop_loss=round(px * 0.88, 2), target=0))
                        print(f"  📈 买 {code} {shares}股 @{px:.2f} (实时价) 评分{score:.3f}")
        # 重评日标记：只在窗口到期（is_re）时更新（2026-08-18 修复：原在买入块内，
        # 每日补仓会误重置 last_rebalance_date，导致重评窗口永远不触发）
        if is_re:
            acct.config['last_rebalance_date'] = str(trade_date)

    # ── NAV 实时价估值（拉不到实时价用成本价兜底）──
    pos_val = sum(p.shares * (rtp.get(p.code) or p.avg_cost) for p in acct.positions)
    nav = acct.cash + pos_val
    # 当日收益基准 = 今天之前最后一条 NAV（当天多次运行不重复累计）
    today = trade_date
    prev_hist = [h for h in acct.nav_history if str(h.get('date', '')).replace('-', '') != today]
    prev = prev_hist[-1].get('nav') if prev_hist else INIT_CAPITAL
    daily_ret = round((nav / prev - 1) * 100, 4) if prev > 0 else 0.0
    # ⚠️ 异常值防护（2026-08-15 修复：Sina 实时价偶发异常 → daily_ret 爆表写入残留）
    # 单账户单天日收益超过 ±30% 必为异常（A股单日涨跌停 ±10~20%，含重仓杠杆也不超过 ±30%）
    nav_ok = abs(daily_ret) <= 30
    if not nav_ok:
        print(f"  ⚠️ {aid} daily_ret={daily_ret:.2f}% 异常（实时价瞬变），本次 NAV 不落库（交易已保存）")
    # market_ret 同样防护（市场指数单日不可能超 ±30%，Sina 偶发返回异常昨收）
    if mkt_ret is not None and abs(mkt_ret) > 30:
        print(f"  ⚠️ {aid} market_ret={mkt_ret:.2f}% 异常（指数实时价瞬变），用 0 替代")
        mkt_ret = 0.0
    # 交易先保存（异常时也不丢成交记录）
    store.save(acct)
    if not nav_ok:
        return acct, nav, None
    acct.record_nav(rtp)  # 实时价估值（同一天 key 只更新不新增）
    store.save(acct)
    state.execute("""
        INSERT OR REPLACE INTO strategy_accounts
        (account_id, date, nav, cash, pos_value, daily_ret, market_ret, n_pos)
        VALUES (?,?,?,?,?,?,?,?)
    """, (aid, trade_date, round(nav, 2), round(acct.cash, 2), round(pos_val, 2),
          daily_ret, mkt_ret, len(acct.positions)))
    state.commit()
    return acct, nav, daily_ret


def report(state, tushare):
    """输出三账户对比报告"""
    print("\n════════ 策略账户对比 ════════")
    rows = state.execute("""
        SELECT account_id, MAX(date) FROM strategy_accounts GROUP BY account_id
    """).fetchall()
    if not rows:
        print("尚无数据，先运行主程序建仓")
        return
    for aid, d in rows:
        hist = state.execute("""
            SELECT date, nav, daily_ret FROM strategy_accounts
            WHERE account_id=? ORDER BY date
        """, (aid,)).fetchall()
        last_nav = hist[-1][1]
        total = (last_nav / INIT_CAPITAL - 1) * 100 if INIT_CAPITAL else 0
        name = ACCOUNTS[aid]['name']
        print(f"\n{name} ({aid})  最新 {d}  NAV={last_nav:,.0f}  累计{total:+.2f}%")
        for dt, nav, dr in hist[-5:]:
            print(f"    {dt}  NAV={nav:,.0f}  当日{dr:+.2f}%")


def main():
    args = sys.argv[1:]
    do_report = '--report' in args

    store = AccountStore()
    state = sqlite3.connect(str(STATE_DB), timeout=30)  # v2: 主连=ledger.db
    state.execute("ATTACH DATABASE ? AS sig", (str(SIGNALS_DB),))
    ensure_nav_table(state)
    tushare = duckdb.connect(str(TUSHARE_DB), read_only=True)
    bad_codes = get_filtered_codes(tushare)

    if do_report:
        report(state, tushare)
        state.close(); tushare.close()
        return

    now = datetime.now()
    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：非交易日不落 NAV 行
    from core.trade_calendar import assert_trading_day
    assert_trading_day('策略账户日更')
    # 交易时段检查（统一口径: 9:30-11:30 / 13:00-15:00，见 core/trading_time.py）
    # 非交易时段无实时价，禁止交易
    from core.trading_time import in_trading_session
    if not in_trading_session(now):
        print(f"[{now.strftime('%H:%M:%S')}] 非交易时段，跳过（策略账户只在交易时段按实时价成交）")
        state.close(); tushare.close()
        return

    today = now.strftime('%Y%m%d')
    # 新账户最早可交易日门槛
    if today < START_DATE:
        print(f"未到最早可交易日 {START_DATE}，跳过")
        state.close(); tushare.close()
        return

    # 节假日/非交易日防护：指数实时涨跌幅≈0 视为无行情（Sina 节假日返回昨收价，会失真）
    try:
        idx_px, idx_chg = fetch_price_live('000001')
        if not idx_px or abs(idx_chg) < 0.0001:
            print(f"[{now.strftime('%H:%M:%S')}] 疑似非交易日（指数无实时波动），跳过")
            state.close(); tushare.close()
            return
    except Exception:
        pass

    # 信号日 = 最近一个早于今天的信号日（盘后信号，今天盘中执行）
    d = state.execute(
        "SELECT MAX(REPLACE(date,'-','')) FROM sig.fusion_3f_signals WHERE REPLACE(date,'-','') < ?",
        (today,)).fetchone()[0]
    if not d:
        print("暂无历史信号日，跳过")
        state.close(); tushare.close()
        return

    print(f"\n=== 信号日 {d} → 今日 {today} 实时价调仓 ===")
    mkt = market_ret_realtime()
    # 防御状态机评估（2026-09-16 挂上，core/defense.py）：全场一次评估，各账户共用
    global DMODE
    try:
        _zz_px, _zz_chg = fetch_price_live('000852')
        DMODE, _devt = defense.evaluate(_zz_px, _zz_chg)
        if _devt:
            print(f"🛡️ 防御状态变更: {_devt}")
        elif DMODE != 'normal':
            print(f"🛡️ 防御模式: {DMODE}")
    except Exception as _de:
        DMODE = 'normal'
        print(f"[WARN] 防御状态评估失败(按normal): {_de}")
    failures = 0
    # 2026-09-01 冷却归档：每账户清 60 交易日未买回的 memory 记录（条件腿终点）
    for aid in ACCOUNTS:
        if ACCOUNTS[aid].get('closed'):
            continue  # 2026-09-11 销户账户跳过归档（不再交易，memory 无消费方）
        try:
            td_since = cooldown.count_trading_days_since(tushare, str(today))
            cooldown.expire_memories(state, aid, td_since)
        except Exception as e:
            print(f"  ⚠️ {aid} 冷却归档失败: {e}")
    for aid in ACCOUNTS:
        # 允许交易时段内多次运行：每次按实时价检查调仓（持仓已对齐则无操作），
        # NAV 用 INSERT OR REPLACE 同一天覆盖更新，最后一次(收盘时点)为当日终值
        if ACCOUNTS[aid].get('closed'):
            continue  # 2026-09-11 销户（三因子系）：不再交易，NAV/持仓冻结在最后交易日
        print(f"  [{ACCOUNTS[aid]['name']}]")
        try:
            run_day(store, state, tushare, d, today, aid, bad_codes, mkt)
        except Exception as e:
            print(f"  ⚠️ {aid} 失败: {e}")
            failures += 1
    if failures:
        # 2026-08-24 加固：任何账户失败必须 exit 1 → cron error 告警。
        # 原代码异常被吞 exit 0（cron 显示 ok），8/24 prev_map 崩溃 5 轮无告警
        # 且每 10 分钟重复卖出累积——有告警第一轮就会暴露。
        print(f"❌ {failures}/{len(ACCOUNTS)} 账户失败，exit 1（告警）")
        report(state, tushare)
        state.close(); tushare.close()
        sys.exit(1)

    report(state, tushare)
    state.close(); tushare.close()

    # ── 派生显示层自愈（2026-09-17）──
    # 策略账户权威源是 ledger.db，sim_accounts/*.json 是 AccountStore.save() 导出的派生显示层
    # （面板持仓页读它）。手动/离线改账若绕过 save() 直写 DB，JSON 就会滞后（2026-09-16 事故）。
    # 这里每轮收尾按 DB 单向重导出**仅漂移的**账户（DB→JSON，永不反向覆盖 DB），带 .bak。
    try:
        from core.derived_export import resync_all
        resync_all(verbose=True)
    except Exception as _e:
        print(f"[WARN] 派生层自愈失败（不影响交易与账本）: {_e}")


if __name__ == '__main__':
    main()
