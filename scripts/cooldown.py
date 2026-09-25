#!/usr/bin/env python3
"""卖出冷却 + 止损记忆（2026-09-01 用户拍板：时间+价格+模型三腿）。

背景: 中岩大地 8/31 止损后同 tick 买回、联创光电 15 天霸榜越跌越高分——
止损白卖的循环。冷却机制只约束"止损出清"后的再买入，止盈/重建/部分减仓不触发。

规则（三腿，全部通过才放行）:
  腿一 时间: 止损后冷却期（策略账户=到重评日，重评日清时间腿；主账户=10 交易日）
             ——期内绝对禁买（防同 tick 买回，条件腿在同 tick 下全满足拦不住）
  腿二 价格: 冷却期满后 现价 ≥ 止损卖出价（价格必须证明自己，不接下跌中的刀）
  腿三 模型: score ≥ 卖出时 score（模型不能比止损时更弱；注意"score 创新高"是错的——
             越跌越高分，创新高=更超跌，故用"不低于卖出时"而非"创新高"）

状态流转: cooldown(时间腿内) --重评日/10交易日--> memory(条件腿) --买回--> 删除
二次止损: UPSERT 覆盖（最近一次止损为准）；卖出后 60 交易日未买回自动归档（调用方清理）。
"""
import sqlite3
from datetime import datetime

STOP_REASON_MARK = '止损'      # reason 含此标记 → 止损类卖出，触发冷却
COOLDOWN_DAYS_MAIN = 10        # 主账户时间腿：10 个交易日
MEMORY_EXPIRE_DAYS = 60        # 记忆归档：60 个交易日未买回
# 止盈类卖出（策略 R6 回撤止盈 / 主账户 达目标价·回撤止盈）后禁买回交易日数
# （2026-09-02 用户拍板：触发止盈止损的票不管是否在名单上都禁买回；单一来源——策略账户与
#  主账户共用此常量。N=1 = 仅卖出当日禁，次日仍上榜由买入逻辑重新接回；"禁几天"待定后改此值。）
TP_REENTRY_BAN_DAYS = 1

DDL = """
CREATE TABLE IF NOT EXISTS trade_cooldown (
    code        TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    sell_date   TEXT NOT NULL,      -- 止损出清日 YYYYMMDD
    sell_price  REAL NOT NULL,      -- 止损卖出价（出清加权均价）
    sell_score  REAL,               -- 卖出时信号分
    status      TEXT NOT NULL DEFAULT 'cooldown',  -- cooldown|memory
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (code, strategy)
)
"""


def ensure_table(conn: sqlite3.Connection):
    conn.execute(DDL)
    conn.commit()


def is_stop_reason(reason) -> bool:
    """止损类卖出判定（止盈/重建/评分转负等非止损不进冷却）"""
    return bool(reason) and STOP_REASON_MARK in str(reason)


def add_stop_memory(conn: sqlite3.Connection, code: str, strategy: str,
                    sell_price: float, sell_score, sell_date: str):
    """止损出清 → 写冷却+记忆（UPSERT 覆盖，二次止损以最近一次为准）"""
    conn.execute(
        """INSERT INTO trade_cooldown (code, strategy, sell_date, sell_price, sell_score, status)
           VALUES (?, ?, ?, ?, ?, 'cooldown')
           ON CONFLICT(code, strategy) DO UPDATE SET
             sell_date=excluded.sell_date, sell_price=excluded.sell_price,
             sell_score=excluded.sell_score, status='cooldown',
             created_at=datetime('now','localtime')""",
        (code, strategy, sell_date, sell_price, sell_score))
    conn.commit()


def check_cooldown(conn: sqlite3.Connection, code: str, strategy: str,
                   current_price: float, current_score,
                   *, is_re: bool = False, clear_time_leg: bool = False) -> tuple:
    """买入前检查（2026-09-01 改全局版：按 code 查该股全部账户的冷却记录，任一命中即拦）。
    返回 (blocked, reason)。

    跨账户横跳修复：600363 仅 main 止损 → fusion_dual 名下无记录但照样拦
    （per-account 查询漏掉跨账户接刀，9/1 实盘 fusion_dual 16.32 买回 main 8/31 止损的 16.37）。

    时间腿：以【卖出账户】类型为准，全体账户共享——
      main 记录：count_signal_days_since ≥ 10 信号日
      策略账户记录：到该策略自己的重评日（clear_time_legs 批量清 time 腿转 memory）
    价格腿：现价 ≥ 该 code 所有记录的最高止损卖出价（最严）
    模型腿：仅同 strategy 记录可比（跨账户评分尺度不同不强比，价格腿兜底）
    is_re/clear_time_leg：买入方重评日——只清买入账户自己名下记录的时间腿，
      其他账户（如 main）的记录不因本账户重评日放行。
    """
    rows = conn.execute(
        "SELECT sell_date, sell_price, sell_score, status, strategy FROM trade_cooldown WHERE code=?",
        (code,)).fetchall()
    if not rows:
        return False, ''

    # 买入账户自己名下是否有记录（重评日可清自己的时间腿）
    my_rows = [r for r in rows if r[4] == strategy]

    # ── 腿一 时间：逐条记录按其卖出账户类型判断 ──
    for sell_date, sell_price, sell_score, status, rstrat in rows:
        if status != 'cooldown':
            continue  # 已转 memory（时间腿已过），只看条件腿
        time_leg_done = False
        if rstrat == strategy and (is_re or clear_time_leg):
            time_leg_done = True  # 买入方重评日：清自己名下记录的时间腿
        elif rstrat == 'main':
            n = count_signal_days_since(conn, sell_date)
            time_leg_done = n >= COOLDOWN_DAYS_MAIN  # main 记录：10 信号日满
        # 其他策略账户记录：重评日未到 → 时间腿未满（不因买入方重评日放行）
        if not time_leg_done:
            return True, f'冷却期内({rstrat} {sell_date} 止损，禁买)'

    # 时间腿全解除 → 相关记录转 memory（条件腿继续）
    for sell_date, sell_price, sell_score, status, rstrat in rows:
        if status == 'cooldown':
            conn.execute("UPDATE trade_cooldown SET status='memory' WHERE code=? AND strategy=?",
                         (code, rstrat))
    conn.commit()

    # ── 腿二 价格：现价 ≥ 全部记录最高止损卖出价（最严）──
    max_sell_price = max(r[1] for r in rows)
    if current_price is not None and current_price < max_sell_price:
        return True, f'价格未回最高止损价({max_sell_price:.2f}，现价{current_price:.2f})'

    # ── 腿三 模型：仅同策略记录可比（跨账户尺度不同不强比）──
    for sell_date, sell_price, sell_score, status, rstrat in my_rows:
        if current_score is not None and sell_score is not None and current_score < sell_score:
            return True, f'score未达卖出时({sell_score:.1f}，现{current_score:.1f})'

    # 全部通过 → 买回 → 删除【本账户】记忆（其他账户记录保留，各自条件腿仍有效）
    conn.execute("DELETE FROM trade_cooldown WHERE code=? AND strategy=?", (code, strategy))
    conn.commit()
    return False, ''


def clear_time_legs(conn: sqlite3.Connection, strategy: str):
    """重评日清空某账户全部时间腿（cooldown → memory，条件腿继续）"""
    conn.execute("UPDATE trade_cooldown SET status='memory' WHERE strategy=? AND status='cooldown'",
                 (strategy,))
    conn.commit()


def expire_memories(conn: sqlite3.Connection, strategy: str, trading_days: int):
    """归档超期记忆（卖出后 >60 交易日未买回）"""
    if trading_days >= MEMORY_EXPIRE_DAYS:
        conn.execute("DELETE FROM trade_cooldown WHERE strategy=? AND status='memory'", (strategy,))
        conn.commit()


def count_signal_days_since(conn, date_from: str) -> int:
    """主账户冷却期计数：signal_history 中 sell_date 后的信号日数（≈交易日，信号日=交易日）。
    M2=单库(signal_history)；MacBook v2=signals.db 经 sig. 前缀——两版都试。"""
    for tbl in ('signal_history', 'sig.signal_history'):
        try:
            n = conn.execute(
                f"SELECT COUNT(DISTINCT REPLACE(date,'-','')) FROM {tbl} WHERE REPLACE(date,'-','') > ?",
                (str(date_from),)).fetchone()[0]
            if n is not None:
                return int(n or 0)
        except Exception:
            continue
    return 0


# ─────────────────────────────────────────────────────────────
# 止盈(R6 回撤止盈)卖出后的短期禁买回（2026-09-02 用户拍板：触发止盈止损的票不管是否在
# top10 名单上都禁买回——安全规则不因"模型还想要"豁免；止损类走上面的三腿冷却（到重评日/
# 10 信号日，比止盈禁买更严），止盈类走本表，禁 N 个交易日后自然过期。
# 本表按 (code, strategy) 独立：止盈≠接刀风险，不跨账户共享（跨账户接刀由止损全局冷却管）。
# ─────────────────────────────────────────────────────────────
TP_BAN_DDL = """
CREATE TABLE IF NOT EXISTS trade_tp_ban (
    code        TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    sell_date   TEXT NOT NULL,      -- 止盈卖出日 YYYYMMDD
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (code, strategy)
)
"""


def ensure_tp_ban_table(conn: sqlite3.Connection):
    conn.execute(TP_BAN_DDL)
    conn.commit()


def add_tp_ban(conn: sqlite3.Connection, code: str, strategy: str, sell_date: str):
    """回撤止盈卖出 → 记禁买（UPSERT：二次止盈以最近一次为准）"""
    conn.execute(
        """INSERT INTO trade_tp_ban (code, strategy, sell_date)
           VALUES (?, ?, ?)
           ON CONFLICT(code, strategy) DO UPDATE SET
             sell_date=excluded.sell_date, created_at=datetime('now','localtime')""",
        (code, strategy, sell_date))
    conn.commit()


def check_tp_ban(conn: sqlite3.Connection, tushare, code: str, strategy: str,
                 trade_date: str, ban_days: int) -> tuple:
    """止盈禁买检查（tushare.daily 算卖出日之后已过交易日数，卖出日=0；含今日盘中补 1，
    与 is_re/_pos_expired 同口径）。返回 (blocked, reason)。期满自动删记录。"""
    r = conn.execute(
        "SELECT sell_date FROM trade_tp_ban WHERE code=? AND strategy=?",
        (code, strategy)).fetchone()
    if not r:
        return False, ''
    sd = str(r[0]).replace('-', '')
    try:
        n = tushare.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?",
            (sd,)).fetchone()[0]
        latest_daily = tushare.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
        elapsed = int(n or 0)
        if latest_daily and str(latest_daily) < str(trade_date) and str(trade_date) != sd:
            elapsed += 1
    except Exception:
        elapsed = 999  # 查不到按期满放行（止损仍有冷却兜底，止盈禁买是纪律非风控底线）
    if elapsed >= ban_days:
        conn.execute("DELETE FROM trade_tp_ban WHERE code=? AND strategy=?", (code, strategy))
        conn.commit()
        return False, ''
    return True, f'止盈禁买期({sd} 回撤止盈卖出，已过{elapsed}/{ban_days}交易日)'


def check_tp_ban_signal(conn: sqlite3.Connection, code: str, strategy: str,
                        ban_days: int) -> tuple:
    """主账户版止盈禁买检查：elapsed 用 signal_history 信号日计数（与其止损冷却 10 信号日
    同口径；M2=signal_history / MacBook v2=sig.signal_history 双兼容）。信号日晚于交易日入库，
    到期比 daily 版晚 ≤1 个交易日（更保守——主账户真实资金，方向安全）。
    返回 (blocked, reason)，期满自动删记录。"""
    r = conn.execute(
        "SELECT sell_date FROM trade_tp_ban WHERE code=? AND strategy=?",
        (code, strategy)).fetchone()
    if not r:
        return False, ''
    sd = str(r[0]).replace('-', '')
    try:
        elapsed = count_signal_days_since(conn, sd)
    except Exception:
        elapsed = 999  # 查不到按期满放行（止损冷却仍兜底）
    if elapsed is None:
        elapsed = 999
    if elapsed >= ban_days:
        conn.execute("DELETE FROM trade_tp_ban WHERE code=? AND strategy=?", (code, strategy))
        conn.commit()
        return False, ''
    return True, f'止盈禁买期({sd} 卖出，已过{elapsed}/{ban_days}信号日)'


def count_trading_days_since(tushare, date_from: str) -> int:
    """（备用）tushare daily 交易日计数"""
    try:
        n = tushare.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?",
            (str(date_from),)).fetchone()[0]
        return int(n or 0)
    except Exception:
        return 0
