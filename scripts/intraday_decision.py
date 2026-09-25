#!/usr/bin/env python3
"""
盘中决策层 — 读取数据库观察名单，生成待执行订单
==================================================
功能：
1. 盘中每 5-10 分钟运行
2. 读取 ledger.db.watchlist (status=watch_active, v2热层)
3. 获取实时价格 + 持仓状态
4. 应用风控规则 (止损/止盈/评分/行业限制)
5. 生成 orders/pending.json (交易指令)

输出格式:
    orders/pending.json
    {
      "timestamp": "2026-07-19 10:30:00",
      "signals": [
        {
          "stock_code": "600508",
          "action": "BUY",
          "shares": 31000,
          "price": 8.10,
          "reason": "评分 100，年线附近",
          "signal_score": 100.0
        },
        {
          "stock_code": "300680",
          "action": "SELL",
          "shares": 9900,
          "reason": "硬止损 -12.5%",
          "signal_score": 45.0
        }
      ]
    }
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import time
from datetime import datetime, date
from typing import List, Dict, Optional
import sqlite3
import numpy as np

from core.db import TUSHARE_DB_PATH
from core.hold_days import calc_holding_days  # 交易日口径（2026-08-07 与面板共用单一实现）
import cooldown  # 卖出冷却+止损记忆（2026-09-01：时间/价格/模型三腿）
from core import defense  # 防御状态机（2026-09-16 用户拍板"挂上"：halved/crash2 两档，见 core/defense.py）

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'ledger.db'       # v2热层: holdings/watchlist/account_balance/position_peaks
SIGNALS_DB = BASE / 'signals.db'    # v2温层: signal_history/fusion_3f_signals/tdx_*(ATTACH为sig)

def _db_conn(timeout=10):
    """v2: 主连ledger.db + ATTACH signals.db 为 sig.，跨层查询用 sig. 前缀"""
    c = sqlite3.connect(str(STATE_DB), timeout=timeout)
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("ATTACH DATABASE ? AS sig", (str(SIGNALS_DB),))
    return c
PENDING_FILE = BASE / 'orders' / 'pending.json'

# ── 配置 ─────────────────────────────────────────────────────
MIN_SCORE = 70          # 评分≥70 才买入
MAX_PX_DEV = 0.095      # 非涨跌停 (<9.5%)
MAX_MARKET_DROP = 1.5   # 大盘非大跌日
MAX_PER_INDUSTRY = 2    # 单行业不超过 2 只
# 2026-09-11 用户拍板（L3）：整梯级放宽 3 个点。证据：-12% 硬止损 14 笔卖后 5 日中位
#   +6.81%、62% 上涨、卖价低于当日收盘 2.13%（砸在破位最低点，T+1 只能次日）→ 放宽；
#   且 8/31 加了 -9% 加速止损后它会先于 -12% 触发，只放宽硬止损是空操作 → 同步放宽两档。
#   ⚠️ T+2 周（约 2026-09-25）复核：若放宽后浮亏尾部扩大则回退（两台同改）。
HARD_STOP = -15.0       # 硬止损 -15%（2026-09-11：原 -12%）
ACCEL_STOP = -12.0      # 加速止损 -12%（2026-09-11：原 -9%，无条件立即卖）
STOP_CONFIRM_TIME = '14:30'  # R4 跌破止损尾盘确认（2026-08-31：开盘破位立即卖，否则 14:30 后卖）
FLOAT_STOP_FLOOR = 0.94  # 扫描止损价下限 = 成本×0.94（2026-08-31 修正：止损不会比成本 -6% 更紧，
                         # 与策略账户 R7 浮亏止损 -6%（2026-08-29 用户批准）同尺度）
TARGET_EXIT_DAYS = 5    # 达目标价后至少持有 5 天
HOLD_DAYS = 20          # 持仓满 20 天 + 评分<30 则卖
HOLD_PNL_THRESHOLD = 8.0  # 规则5B 盈亏阈值（2026-08-18 用户拍板：持仓≥20天+评分<30+盈亏<8% → 超期低分横盘卖出）
RULE5C_HOLD_DAYS = 30   # 规则5C（2026-09-15 用户拍板）：持仓≥30交易日 且 融合分fusion<0 → 无条件清仓，
                        #   盈亏豁免不适用（5B 的"盈亏<8%"豁免会漏掉盈利但模型转负的仓位——实例：
                        #   301557 常友科技持32天融合分连负三天，+14%浮盈无任何规则管）。
                        #   30天>10d重评窗口、不到40d融合分预测窗口一半，给足时间且要求模型按自身
                        #   40日口径否定才动手；融合分≥0 的长牛票不受影响。
SCORE_DROP_DAYS = 10    # 评分连降 10 天 + 跌破成本
SCORE_DROP_THRESHOLD = 55  # 跌破此评分
# 回撤保护（2026-08-05 新增，参照策略账户 R6）：
#   峰值≥成本×1.05（先浮盈5%）且 现价≤峰值×0.92（从峰值回撤8%）→ 卖
DRAWDOWN_MIN_GAIN = 1.05   # 峰值须达成本 1.05 倍才启用
DRAWDOWN_RATIO = 0.92      # 现价 ≤ 峰值×0.92（回撤 8%）触发
DRAWDOWN_MARKET_THRESHOLD = -2.0  # 条件式回撤止盈（2026-08-20 用户拍板）：当日大盘跌幅 ≤ -2% 才启用
#   回测（7个月3714样本）：无条件8%回撤 t=-4.23 显著劣于持有（普涨市卖飞）；
#   加"当日大盘≤-2%"开关后 t=+0.80（不再有害，微正），下跌市保护方向保留（-0.12 vs -0.19）。
# 总量护栏（2026-08-07 新增，用户批准）：
#   ① 持仓总数上限——防止无限累积满仓（8/7 已 35 只满仓、现金枯竭至 1807）
#   ② 现金下限=总资产比例——保证流动性，低于此值整轮跳过买入
# 2026-09-11 用户拍板（L1）：25 只顶死硬上限 → 现金闲置 14.8%、最近 25 次决策 18 次
#   「已达硬上限跳过买入」、单票最高仅 8.5% 使 20% 集中度上限空转 → 收敛到 12 只（提高单票权重
#   与资金效率）。过渡：存量 25 只不强制卖，靠风控卖出自然衰减；持仓 > 硬上限期间不新买。
# 2026-09-21 用户拍板（解闸）：12/15 → 20/25（恢复 8/26 满仓拍板值）。原因：收敛后主账户
#   存量 16 只 > 硬顶 15 → 买入通道被存量卡死、现金 44.3万（35.7%）无路可走 = 变相长期降仓位，
#   与"非熊市/股灾就满仓运作"原则冲突。且"控碎仓"的正确工具是买入权重口径（同日已修：
#   get_position_sizing 基数 cash→NAV + NAV×2.5% 最小权重门槛），不是压缩只数上限 —— 后者
#   反而使每笔买入缩水到设计权重 36%。回滚：把下面两行改回 12 / 15。
MAX_POSITIONS = 20         # 持仓总数软上限（现金>5%时可超，见 HARD_MAX_POSITIONS）
HARD_MAX_POSITIONS = 25    # 持仓总数硬上限（2026-09-21 解闸 15→25；9/11 曾 25→15）
MIN_CASH_RATIO = 0.02      # 现金下限 = 总资产 2%
MAX_POSITION_RATIO = 0.20  # 单票集中度上限 = 总资产 20%（2026-08-16 用户批准）
MIN_POSITION_RATIO = 0.025 # 最小建仓权重 = 总资产 2.5%（2026-09-21 用户拍板：防碎仓 ——
                           #   实际能买金额 < NAV×2.5% 时返回 0 留现金，不再用残值建小仓）

# 评分对应仓位
POSITION_SCALE = [
    (85, 0.15, '高置信 15%'),
    (78, 0.10, '中置信 10%'),
    (70, 0.05, '低置信 5%'),
    (0,  0.00, '不建仓'),
]

def get_live_price(code: str) -> tuple:
    """获取实时价格（仅实时源，不用 DB 收盘价兜底）"""
    from core.prices import fetch_price_live
    try:
        price, change = fetch_price_live(code)
        if price and price > 0:
            return price, change
    except:
        pass
    return None, 0

def get_live_open(code: str):
    """获取当日开盘价（2026-08-08 低吸信号: 开盘走强确认用）"""
    from core.prices import fetch_price_open
    try:
        return fetch_price_open(code)
    except:
        return None

def get_live_prev(code: str):
    """获取昨收价（2026-08-08 高开 gap 计算用）"""
    from core.prices import fetch_price_prev
    try:
        return fetch_price_prev(code)
    except:
        return None

def _log_tdx_signal(log_date, signal_date, code, signal_type, action, price, account='main'):
    """TDX 信号交易归因日志（2026-08-08 用户要求: 策略交易全部统计）"""
    try:
        c = _db_conn(timeout=5)
        c.execute("INSERT INTO sig.tdx_signal_log (log_date, signal_date, code, signal_type, action, price, account) VALUES (?,?,?,?,?,?,?)",
                  (log_date, signal_date, code, signal_type, action, price, account))
        c.commit()
        c.close()
    except Exception:
        pass

def get_market_status() -> tuple:
    """检查大盘状态（Sina API 实时）"""
    try:
        from core.prices import fetch_price_live
        price, change = fetch_price_live('000001')
        if price and price > 0:
            return change, price
    except:
        pass
    return 0, 0

def get_industry(code: str) -> str:
    """查 stock_basic 表获取行业"""
    try:
        conn = _db_conn(timeout=10)
        r = conn.execute(f"SELECT industry FROM sig.stock_basic WHERE stock_code='{code}'").fetchone()
        conn.close()
        if r and r[0] and len(r[0]) >= 2:
            return r[0][:3]
    except:
        pass
    return 'ZZZ'

def bump_industry(industry_counts: Dict, code: str):
    """L4（2026-09-11）：同一 tick 内买入后累加行业计数。

    原实现只在 tick 开始时按存量算一次 industry_counts，循环内买入不累加 →
    同一 tick 连买同行业 2 只都会通过（各自看到的计数都是初始值）→ 存量冲到 3 只
    （实测：主账户电气设备 3 只 > MAX_PER_INDUSTRY=2）。
    """
    ind = get_industry(code)
    industry_counts[ind] = industry_counts.get(ind, 0) + 1


def get_position_sizing(cash: float, total_value: float, price: float, score: float, market_chg: float,
                        code: str = '', defense_mode: str = 'normal') -> tuple:
    """计算仓位和股数

    2026-09-21 修复（用户拍板，防碎仓）—— 与 M2 同源修复：
      原实现 `max_amt = cash * actual_pct` 的**基数是「现金」而非「总资产」**。现金被消耗后
      （实况 44.27万/NAV 123.9万 = 35.7%）每笔买入缩水到设计值 36%：评分 70 设计 5%×NAV=6.2万，
      实际只买 5%×现金=2.2万（NAV 的 1.8%）→ 碎仓，且现金越少越碎。
      修法① 基数改 total_value + 现金夹逼 min(NAV×pct, cash)；
      修法② 能买金额 < NAV×MIN_POSITION_RATIO(2.5%) → 返回 0 留现金。
      防御态折扣 d_coef（2026-09-16）保留。只改新买入金额，不动卖出/风控/上限。
      回滚：max_amt 改回 `cash * actual_pct`，并删掉门槛判断那两行。
    """
    base_pct = 0
    label = '不建仓'
    for threshold, pct, desc in POSITION_SCALE:
        if score >= threshold:
            base_pct, label = pct, desc
            break
    
    # 大盘系数
    mkt_coef = 1.0
    if market_chg < -1.0:
        mkt_coef = 0.8
    # 防御态新开仓折扣（2026-09-16 挂上：halved/crash2 仓位×0.5，见 core/defense.py）
    d_coef = defense.buy_scale(defense_mode)

    actual_pct = base_pct * mkt_coef * d_coef
    max_amt = min(total_value * actual_pct, cash)   # 目标权重按总资产；受可用现金夹逼
    if max_amt < total_value * MIN_POSITION_RATIO:  # 防碎仓：买不足 NAV×2.5% 就不买
        return 0, label
    # 按股价算实际可买股数（A股100股整数倍）
    # 2026-08-07: 去掉 max(...,100) 兜底——现金买不起 100 股×目标仓位时返回 0（调用方跳过），
    # 不再强制 100 股超买（实盘案例：8/7 买入 301172 现金3563 设计534元 实买1755=49%）
    if price > 0:
        shares = int(max_amt / price / 100) * 100
    else:
        shares = 0
    # 2026-08-31 硬校验：科创(68)/创业(30) 板最低申报 200 股，<200 返回 0（调用方跳过）
    if (code.startswith('30') or code.startswith('68')) and 0 < shares < 200:
        return 0, label
    return shares, label

def check_sell_conditions(code: str, pos: Dict, current_price: float, score: float,
                          market_chg: float = 0.0,
                          fusion_score: Optional[float] = None,
                          defense_mode: str = 'normal',
                          in_cut_set: bool = False) -> Optional[tuple]:
    """检查卖出条件，返回 (action, reason)"""
    cost = pos.get('avg_cost', 0)
    shares = pos.get('shares', 0)
    buy_date = pos.get('buy_date', '')
    
    if shares == 0 or cost == 0:
        return None
    
    # T+1 制度：当日买入不可当日卖出（2026-08-03 用户要求；真实约束：当天买入的票
    # 触发止损也卖不掉，止损单只能次日生效。直接比 buy_date 与今天，不依赖 index_daily 数据滞后）
    if buy_date and buy_date[:10] == datetime.now().strftime('%Y-%m-%d'):
        return None
    
    pnl = (current_price / cost - 1) * 100
    hold_days = calc_holding_days(buy_date)
    
    # 规则 1: 硬止损 -12%（无条件立即卖——尾部风险防线，不等尾盘，抢跌停前离场）
    if pnl <= HARD_STOP:
        return ('SELL', f'硬止损{pnl:.1f}%')
    
    # 规则 1B: 加速止损 -9%（2026-08-31 新增：浮亏止损-6% 与硬止损-12% 之间的恶化确认——
    # 从 -6% 继续跌到 -9% = 不是假摔，无条件立即卖，不等尾盘）
    if pnl <= ACCEL_STOP:
        return ('SELL', f'加速止损{pnl:.1f}%')
    
    # 规则 2: 达目标价 + 持有≥5 天
    target = pos.get('target_price', pos.get('target', 0))
    if target > 0 and current_price >= target and hold_days >= TARGET_EXIT_DAYS:
        return ('SELL', f'达目标价{target:.2f}')
    
    # 规则 3: 条件式回撤保护（2026-08-05 新增，参照策略账户 R6；2026-08-20 加市场开关）
    # 峰值≥成本×1.05（先浮盈5%）且 现价≤峰值×0.92（从峰值回撤8%）且 当日大盘≤-2% → 落袋
    # （无条件回测 t=-4.23 卖飞；加当日大盘≤-2% 开关后 t=+0.80，下跌市保护保留）
    peak = pos.get('peak_price', 0) or cost
    if (peak >= cost * DRAWDOWN_MIN_GAIN and current_price <= peak * DRAWDOWN_RATIO
            and market_chg <= DRAWDOWN_MARKET_THRESHOLD):
        drawdown = (current_price / peak - 1) * 100
        return ('SELL', f'回撤止盈{drawdown:.1f}%(峰值{peak:.2f},大盘{market_chg:+.1f}%)')
    
    # 规则 5D（2026-09-16 用户拍板"挂上"）：防御态清票。
    #   crash2 减仓清单（按 fusion 升序排到市值≤5成）→ 整仓卖；
    #   halved/crash2 下 fusion<3 → 清出（防守砍的不是亏最多的，是模型最不看好的；
    #   fusion=None 不误杀）。T+1 与暴跌日跳过逻辑沿用调用方既有分支。
    if in_cut_set:
        return ('SELL', f'防御减仓crash2(fusion{fusion_score if fusion_score is not None else "?"})')
    if defense.defense_kill_fusion(defense_mode, fusion_score):
        return ('SELL', f'防御清票fusion{fusion_score:.1f}<3(模式{defense_mode}) 盈亏{pnl:+.1f}%')

    # 规则 4: 跌破止损价（2026-08-31 修正 + 尾盘确认：原扫描止损=介入区间下轨，与买入成本脱钩——
    # 买入价高于扫描参考价时止损相对成本过紧，8/27 匠心家居 -5.1% 被洗出（扫描 33.52 vs 成本 35.09）。
    # 止损价 = min(扫描 stop_loss, 成本×FLOAT_STOP_FLOOR)：止损永不比成本 -6% 更紧；
    # 扫描支撑位若低于 -6% 仍生效（更大容错）。
    # 触发后：开盘破位（开盘价已在止损线下=隔夜利空确认）→ 立即卖；平开/高开后盘中跌破
    # → 14:30 尾盘确认卖（8/31 统计 13 笔止损 77% 当日反弹，早盘急跌多为假摔）
    # 防御态收紧：floor 用 defense.float_stop（halved/crash2=-5%，2026-09-16 拍板）
    stop = pos.get('stop_loss', 0)
    floor = cost * defense.float_stop(defense_mode)
    stop_eff = min(stop, floor) if stop > 0 else stop
    if stop_eff > 0 and current_price <= stop_eff:
        try:
            open_p = get_live_open(code)
        except Exception:
            open_p = None
        if open_p is not None and open_p > 0 and open_p <= stop_eff:
            return ('SELL', f'跌破止损{stop_eff:.2f}(开盘破位,成本{cost:.2f})')
        now_ts = datetime.now().strftime('%H:%M:%S')
        if now_ts[:5] >= STOP_CONFIRM_TIME:
            return ('SELL', f'跌破止损{stop_eff:.2f}(尾盘确认,成本{cost:.2f})')
    
    # 规则 5: 评分转负卖出（评分暴跌 + 浮亏 → 走人，避免信号恶化死扛）
    # 条件：评分 < SCORE_DROP_THRESHOLD(55) 且浮亏，或持仓≥HOLD_DAYS(20天)且评分<30
    if score > 0 and score < SCORE_DROP_THRESHOLD and pnl < 0:
        return ('SELL', f'评分转负{score:.0f} 浮亏{pnl:.1f}%')
    # 规则 5B（2026-08-18 用户拍板：阈值 8%）：
    #   持仓≥20天 + 评分<30 + 盈亏<8% → 超期低分横盘卖出（清"老登股"，评分差+横盘占资金）
    #   ⚠️ 原条件 score>0 排除负分持仓（评分越差反而躲过卖出），已去掉——
    #      负分(≤0)同样触发，配合盈亏阈值防止误杀盈利持仓（8/18 实况：24只全盈利但22只评分<30）
    if hold_days >= HOLD_DAYS and score < 30 and pnl < HOLD_PNL_THRESHOLD:
        return ('SELL', f'持仓{hold_days}天 评分{score:.0f}<30 盈亏{pnl:+.1f}%<8%')

    # 规则 5C（2026-09-15 用户拍板）：持仓≥30交易日 + 融合分fusion<0 → 无条件清仓（盈亏豁免不适用）。
    #   5B 的盈亏<8%豁免会让"盈利但模型转负"的仓位无人管（301557 案例）。融合分口径=signal_history
    #   .fusion_score（0.2reg10+0.3reg20+0.5reg40，40日预测窗口）。取不到融合分(None)不误杀。
    if (fusion_score is not None and hold_days >= RULE5C_HOLD_DAYS and fusion_score < 0):
        return ('SELL', f'5C超期融合分转负{fusion_score:.1f} 持{hold_days}天 盈亏{pnl:+.1f}%')

    return None

def check_buy_conditions(code: str, score: float, current_price: float, 
                         change_pct: float, industry_counts: Dict, market_chg: float,
                         entry_low: float = 0, entry_high: float = 0) -> Optional[str]:
    """检查买入条件，返回失败原因或'ok'"""
    # 条件 1: 评分≥70
    if score < MIN_SCORE:
        return f'评分{score:.0f}<{MIN_SCORE}'
    
    # 条件 2: 行业限制
    ind = get_industry(code)
    if industry_counts.get(ind, 0) >= MAX_PER_INDUSTRY:
        return f'{ind}行业已{industry_counts[ind]}只≥{MAX_PER_INDUSTRY}'
    
    # 条件 3: 非涨跌停
    if abs(change_pct) >= 9.5:
        return f'涨跌幅{change_pct:+.1f}%≥9.5%'
    
    # 条件 4: 大盘非大跌
    if market_chg < -MAX_MARKET_DROP:
        return f'大盘跌{market_chg:+.1f}%<{-MAX_MARKET_DROP}%'
    
    # 条件 5: 价格在介入区间内
    if entry_low > 0 and entry_high > 0:
        if current_price < entry_low:
            return f'价{current_price:.2f}<介入下轨{entry_low:.2f}'
        if current_price > entry_high:
            return f'价{current_price:.2f}>介入上轨{entry_high:.2f}'
    
    return 'ok'

def main():
    """主逻辑"""
    now = datetime.now()
    hour = now.hour

    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：非交易日直接退出
    from core.trade_calendar import assert_trading_day
    assert_trading_day('盘中决策')

    # 非交易时段跳过（统一口径: 9:30-11:30 / 13:00-15:00，见 core/trading_time.py）
    from core.trading_time import in_trading_session
    if not in_trading_session(now):
        print(f"[{now.strftime('%H:%M:%S')}] 非交易时段，跳过")
        return
    
    # 检查大盘状态
    market_chg, market_idx = get_market_status()
    print(f"[{now.strftime('%H:%M:%S')}] 大盘{market_chg:+.1f}%")

    # 防御状态机评估（2026-09-16 挂上）：用中证1000实时价判 升级crash2/收复
    try:
        from core.prices import fetch_price_live as _fpl_zz
        _zz_px, _zz_chg = _fpl_zz('000852')
        _dmode, _devt = defense.evaluate(_zz_px, _zz_chg)
        if _devt:
            print(f"🛡️ 防御状态变更: {_devt}")
        elif _dmode != 'normal':
            print(f"🛡️ 防御模式: {_dmode}")
    except Exception as _de:
        _dmode = 'normal'
        print(f"[WARN] 防御状态评估失败(按normal): {_de}")
    
    # 获取持仓（从 ledger.db，v2热层统一数据源）
    holdings = {'positions': []}
    try:
        conn = _db_conn(timeout=10)
        rows = conn.execute(
            "SELECT h.code, h.name, h.buy_date, h.avg_cost, h.shares, h.target_price, h.stop_loss, "
            "COALESCE(p.peak_price, h.avg_cost) "
            "FROM holdings h LEFT JOIN position_peaks p ON p.code = h.code "
            "WHERE h.status='hold'"
        ).fetchall()
        conn.close()
        for r in rows:
            holdings['positions'].append({
                'code': r[0], 'name': r[1], 'buy_date': r[2],
                'avg_cost': r[3], 'shares': r[4], 'status': 'hold',
                'target_price': r[5] or 0, 'stop_loss': r[6] or 0,
                'peak_price': r[7] or r[3]  # 峰值（2026-08-05 回撤保护用）
            })
    except Exception as e:
        print(f"[WARN] 读取 ledger.db.holdings 失败: {e}")
    positions = holdings['positions']
    held_map = {p['code']: p for p in positions}
    
    # 计算行业计数
    industry_counts = {}
    for p in positions:
        ind = get_industry(p['code'])
        industry_counts[ind] = industry_counts.get(ind, 0) + 1
    
    # 清理过期观察名单（超7天或评分<60的自动归档）
    # 注意：scan_date 混存 '20260731'/'2026-07-28' 两种格式，必须 REPLACE 统一为 YYYYMMDD 比较，
    # 否则无横杠日期永远 > 有横杠日期，过期 pending 永不归档（28条实锤）
    try:
        c = _db_conn(timeout=10)
        n1 = c.execute("UPDATE watchlist SET status='archived' WHERE status='pending' AND REPLACE(scan_date, '-', '') < REPLACE(date('now', '-7 days'), '-', '')").rowcount
        n2 = c.execute("UPDATE watchlist SET status='archived' WHERE status='pending' AND ts_code IN (SELECT stock_code FROM sig.signal_history WHERE date=(SELECT MAX(date) FROM sig.signal_history) AND final_score < 60)").rowcount
        c.commit()
        c.close()
        if n1 > 0 or n2 > 0:
            print(f"[CLEANUP] 归档: {n1}条超7天, {n2}条评分<60")
    except Exception as e:
        print(f"[CLEANUP] 清理失败: {e}")

    # 2026-09-01 冷却归档（主账户）：清 60 交易日未买回的 memory 记录（条件腿终点）
    try:
        import duckdb
        c = sqlite3.connect(str(STATE_DB), timeout=10)
        tushare_cd = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
        td_since = cooldown.count_trading_days_since(tushare_cd, datetime.now().strftime('%Y%m%d'))
        cooldown.expire_memories(c, 'main', td_since)
        tushare_cd.close()
        c.close()
    except Exception as e:
        print(f"[COOLDOWN] 冷却归档失败: {e}")

    # 获取观察名单（累积去重：从所有历史数据取每只股票最高分）
    # 同时 JOIN 三因子融合分(fusion_3f_signals) 和 CMMR 分(signal_history.cmmr_score)，
    # 多信号源交叉验证：标注三因子强/CMMR 信号，不设硬门槛（两套体系选股几乎不重叠）
    # 评分阈值：final_score 是百分位(0-100)，取当日 top 10%（>=90）才有区分度
    # 2026-08-27 修复: 原 MAX(w.target_price) 聚合把不同扫描日的 entry/stop/target 混拼
    #   (688636 7/24 target=48.35 异常值被 MAX 捞回, 7/27 已修正 22.4 但买入仍取 48.35)。
    #   改为 ROW_NUMBER 取每只股票"最高分且最新"那次扫描的完整一行(score/entry/stop/target 同源)。
    try:
        conn = _db_conn(timeout=10)
        conn.execute("PRAGMA busy_timeout=15000")
        watch_rows = conn.execute("""
            SELECT ts_code, score, entry_low, entry_high, stop_loss, target_price,
                   f3_score, cmmr_score FROM (
                SELECT w.ts_code, w.score, w.entry_low, w.entry_high, w.stop_loss, w.target_price,
                       COALESCE(f3.fusion_3f_score, 0) as f3_score,
                       COALESCE(sh.cmmr_score, 0) as cmmr_score,
                       ROW_NUMBER() OVER (PARTITION BY w.ts_code
                           ORDER BY w.score DESC, REPLACE(w.scan_date, '-', '') DESC) as rn
                FROM watchlist w
                LEFT JOIN fusion_3f_signals f3
                    ON f3.stock_code = w.ts_code
                    AND REPLACE(f3.date, '-', '') = (
                        SELECT MAX(REPLACE(date, '-', '')) FROM sig.fusion_3f_signals)
                LEFT JOIN signal_history sh
                    ON sh.stock_code = w.ts_code
                    AND REPLACE(sh.date, '-', '') = (
                        SELECT MAX(REPLACE(date, '-', '')) FROM sig.signal_history)
                WHERE w.status = 'pending'
                  AND w.score >= 90
            ) t
            WHERE rn = 1
            ORDER BY score DESC, f3_score DESC
            LIMIT 20
        """).fetchall()
        conn.close()
    except Exception as e:
        print(f"[ERROR] 读取 watchlist 失败：{e}")
        return
    
    signals = []

    # crash2 减仓清单（每 tick 重算：已≤5成 自动为空）——按 fusion 升序整仓卖到市值≤NAV×50%
    cut_set = set()
    if _dmode == 'crash2' and positions:
        try:
            _cb = _db_conn(timeout=5)
            _bal0 = _cb.execute("SELECT cash_balance FROM account_balance WHERE account_id='main'").fetchone()
            _cb.close()
            _cash0 = _bal0[0] if _bal0 and _bal0[0] else 0
            from core.prices import fetch_prices_batch
            _pxs = fetch_prices_batch([p['code'] for p in positions])
            _pp = [{'code': p['code'], 'shares': p['shares'],
                    'price': _pxs.get(p['code']) or p['avg_cost']} for p in positions]
            _cuts, _cmsg = defense.cut_plan(_dmode, _pp, _cash0, defense.get_fusion_map())
            if _cmsg:
                print(f"🛡️ {_cmsg}")
            cut_set = set(_cuts)
        except Exception as _ce:
            print(f"[WARN] crash2 减仓清单失败: {_ce}")
    
    # ── 卖出检查 ─────────────────────────────────────────────
    for p in positions:
        code = p['code']
        price, change = get_live_price(code)
        if not price:
            continue
        
        # 获取评分 (从 signal_history 最新一天 final_score；fallback watchlist)
        # 5C（2026-09-15）同查询带 fusion_score，取不到为 None（不误杀）
        fusion_score = None
        try:
            conn = _db_conn(timeout=10)
            row = conn.execute(f"""
                SELECT final_score, fusion_score FROM sig.signal_history
                WHERE stock_code='{code}'
                  AND REPLACE(date,'-','') = (SELECT MAX(REPLACE(date,'-','')) FROM sig.signal_history)
            """).fetchone()
            conn.close()
            score = row[0] if row and row[0] is not None else 0
            fusion_score = row[1] if row and len(row) > 1 else None
        except:
            score = 0
        
        # 实时更新峰值（2026-08-05 回撤保护：盘中创新高必须更新，否则旧峰值导致过早触发回撤）
        peak = p.get('peak_price') or p['avg_cost']
        if price > peak:
            p['peak_price'] = price
            try:
                conn = _db_conn(timeout=10)
                conn.execute("""
                    INSERT INTO position_peaks (code, peak_price, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET peak_price = MAX(position_peaks.peak_price, ?), updated_at = ?
                """, (code, price, datetime.now().isoformat(), price, datetime.now().isoformat()))
                conn.commit()
                conn.close()
            except Exception:
                pass

        result = check_sell_conditions(code, p, price, score, market_chg,
                                       fusion_score=fusion_score,
                                       defense_mode=_dmode,
                                       in_cut_set=(code in cut_set))
        if result:
            action, reason = result
            # 大盘暴跌日只执行硬止损 + 回撤止盈豁免（2026-08-28 修复：规则3 条件式回撤止盈
            # 要求大盘≤-2%，而暴跌保护在大盘<-1.5% 拦一切非硬止损卖出 → 触发区间空集，规则3 死规则
            # （688175 案例：回撤-13.2% 等大盘-2% 却永远被拦）。回撤止盈是浮盈≥5% 后的利润保护，
            # 暴跌日正是落袋时机，符合 8/20 拍板"下跌市保留保护方向"意图——豁免暴跌保护。
            if market_chg < -MAX_MARKET_DROP and '硬止损' not in reason and '回撤止盈' not in reason \
                    and '防御' not in reason:  # 防御减仓/清票是暴跌确认后的主动去仓，不受暴跌跳过限制（2026-09-16）
                print(f"  ⏭ {code} 大盘暴跌，跳过：{reason}")
                continue
            
            trade_shares = p['shares']
            # 2026-09-01 冷却机制：主账户止损类卖出（reason 含"止损"）→ 写冷却+止损记忆
            if cooldown.is_stop_reason(reason):
                try:
                    _c2 = _db_conn()
                    cooldown.add_stop_memory(_c2, code, 'main', round(price, 3), score,
                                             datetime.now().strftime('%Y%m%d'))
                    _c2.close()
                    print(f"  🧊 {code} 止损出清 → 进冷却（sell@{price:.2f} score={score}）")
                except Exception:
                    pass
            elif reason.startswith('达目标价') or reason.startswith('回撤止盈'):
                # 2026-09-02 止盈类卖出（达目标价/回撤止盈）→ 禁买回（用户拍板：与名单无关，无豁免；
                # 时长 cooldown.TP_REENTRY_BAN_DAYS 单一来源；禁买表建在 ledger.db 主库）
                try:
                    _c2b = _db_conn()
                    cooldown.ensure_tp_ban_table(_c2b)
                    cooldown.add_tp_ban(_c2b, code, 'main', datetime.now().strftime('%Y%m%d'))
                    _c2b.close()
                    print(f"  🛡️ {code} {reason[:16]} → 禁买回{cooldown.TP_REENTRY_BAN_DAYS}交易日")
                except Exception:
                    pass
            signals.append({
                'stock_code': code,
                'action': action,
                'shares': trade_shares,
                'price': price,
                'reason': reason,
                'signal_score': score
            })
            print(f"  💀 {code} {reason} → {trade_shares}股")
    
    # ── 买入检查 (大盘暴跌日不买) ─────────────────────────────
    buy_count = 0  # 本轮买入数（2026-08-28：独立计数，不受卖出信号占用 signals 影响）
    if market_chg >= -MAX_MARKET_DROP:
        # 2026-08-07 总量护栏（用户批准）：
        #   ① 持仓总数上限——防止无限累积满仓（8/7 已 35 只、现金枯竭）
        #   ② 现金下限 MIN_CASH_RATIO=总资产2%——保证流动性，低于此值整轮跳过买入
        # 2026-08-27 修复（满仓原则）: 上限改软硬分层——硬顶 HARD_MAX_POSITIONS 防无限累积;
        #   软顶 MAX_POSITIONS 但现金>5% 时可超（8/26 实况: 卡死+13.6%现金闲置违反满仓拍板）
        # 2026-09-11（L1）：软 12 / 硬 15（原 20/25）
        # 读取现金 + 总资产（account_balance，exec_agent 成交后更新）
        try:
            c = _db_conn(timeout=5)
            bal = c.execute("SELECT cash_balance, total_value FROM account_balance WHERE account_id='main'").fetchone()
            c.close()
            cash = bal[0] if bal and bal[0] else 0
            total_value = bal[1] if bal and bal[1] else 0
        except:
            cash, total_value = 0, 0
        cash_ratio = cash / total_value if total_value > 0 else 0
        min_cash = total_value * MIN_CASH_RATIO
        if len(positions) >= HARD_MAX_POSITIONS:
            print(f"  ⏭ 持仓已达硬上限 {HARD_MAX_POSITIONS} 只（当前 {len(positions)}），跳过买入")
        elif len(positions) >= MAX_POSITIONS and cash_ratio <= 0.05:
            print(f"  ⏭ 持仓 {len(positions)} 只且现金 {cash_ratio*100:.1f}%≤5%，已满仓，跳过买入")
        elif cash < min_cash:
            print(f"  ⏭ 现金 {cash:,.0f} 低于下限 {min_cash:,.0f}（总资产{total_value:,.0f}的2%），跳过买入")
        elif any(p.get('latest_price', 0) * p.get('shares', 0) >= total_value * MAX_POSITION_RATIO
                 for p in positions):
            # 2026-08-16 单票集中度护栏（用户批准）：任一持仓市值 >= 总资产 MAX_POSITION_RATIO
            # 时跳过买入（防止单票过度集中；与总量护栏一致：只拦新买、不强制卖存量）
            conc = [(p['code'], p.get('latest_price', 0) * p.get('shares', 0) / total_value * 100)
                    for p in positions
                    if p.get('latest_price', 0) * p.get('shares', 0) >= total_value * MAX_POSITION_RATIO]
            desc = ' '.join(f"{c}:{r:.0f}%" for c, r in conc)
            print(f"  ⏭ 单票集中度超限（{desc} >= {MAX_POSITION_RATIO*100:.0f}%），跳过买入")
        else:
                # 2026-08-08 TDX 尾盘急拉过滤（执行端接入, 用户批准）:
                # 只排除 VWAP正偏的尾盘急拉(>1.5%)——高位出货式拉升, 次日中位-1.32% (n=9080)
                # VWAP非正偏的急拉=补涨式拉升, 次日+0.43% (n=1874) → 不排除
                # 诱多组合(08-08): 开跌+vwap高+振幅大 → 次日-0.61% (n=23504) → 排除
                # 同连接查低吸候选: 尾盘跌<-0.5% → 开盘走强确认后低吸（1b信号, 次日中位+0.55%）
                # 资金洗盘(08-08): money_flow 最新日净流入 → 低吸高置信标注
                # 恐慌出清(08-08): 尾盘放量下跌(vol_dist_tail>P75=0.149) → 低吸高置信标注
                # 高开观察(08-08): gap>3% 的候选 → 次日偏强(+0.34%), 买入加分标记
                tail30, tail5, low_absorb, entrap, wash, panic = {}, {}, {}, set(), set(), set()
                try:
                    c = _db_conn(timeout=5)
                    dmax = c.execute("SELECT MAX(date) FROM sig.tdx_intraday_feat").fetchone()[0]
                    tail30 = {r[0]: r[1] for r in c.execute(
                        "SELECT code, tail30_ret FROM sig.tdx_intraday_feat "
                        "WHERE date=? AND tail30_ret > 0.015 AND vwap_dev > 0", (dmax,)).fetchall()}
                    # 2026-09-02 分钟线挖掘新增: 最后5分钟急拉>1.5%（不看VWAP）
                    # 命中组次日中位-1.23%, 5/5月为负; 与tail30规则重叠仅111只, 净新增803只
                    tail5 = {r[0]: r[1] for r in c.execute(
                        "SELECT code, tail5_ret FROM sig.tdx_intraday_feat "
                        "WHERE date=? AND tail5_ret > 0.015", (dmax,)).fetchall()}
                    
                    low_absorb = {r[0]: r[1] for r in c.execute(
                        "SELECT code, tail30_ret FROM sig.tdx_intraday_feat "
                        "WHERE date=? AND tail30_ret < -0.005", (dmax,)).fetchall()}
                    panic = {r[0] for r in c.execute(
                        "SELECT code FROM sig.tdx_intraday_feat "
                        "WHERE date=? AND tail30_ret < -0.005 AND vol_dist_tail > 0.149", (dmax,)).fetchall()}
                    entrap = {r[0] for r in c.execute(
                        "SELECT code FROM sig.tdx_intraday_feat "
                        "WHERE date=? AND open30_ret < 0 AND vwap_dev > 0 AND amp_intra > 0.05", (dmax,)).fetchall()}
                    c.close()
                    import duckdb
                    td = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
                    wash = {r[0] for r in td.execute(
                        "SELECT stock_code FROM money_flow "
                        "WHERE date=(SELECT MAX(date) FROM money_flow) AND net_amount > 0").fetchall()}
                    td.close()
                except Exception:
                    pass
                if tail30:
                    print(f"  🚫 尾盘急拉过滤: {len(tail30)} 只昨日急拉>1.5%且VWAP正偏（出货式, 次日不追高）")
                if tail5:
                    extra = len(set(tail5) - set(tail30))
                    print(f"  🚫 最后5分钟急拉过滤: {len(tail5)} 只（净新增 {extra} 只, 尾盘突击诱多）")
                if entrap:
                    print(f"  🚫 诱多组合过滤: {len(entrap)} 只开跌+VWAP高+振幅大（次日中位-1.09%）")
                if low_absorb:
                    print(f"  ✚ 低吸候选: {len(low_absorb)} 只昨日尾盘跌>0.5%（开盘走强确认后低吸）")
                for row in watch_rows:
                    code, score, entry_low, entry_high, stop_loss, target, f3_score, cmmr_score = row
                    if code in held_map:
                        continue
                    price, change = get_live_price(code)
                    if not price:
                        continue
                    # 2026-09-01 冷却机制：主账户买入查三腿（时间腿按信号日计数，_db_conn 带 sig ATTACH）
                    try:
                        _c3 = _db_conn()
                        cooldown.ensure_tp_ban_table(_c3)  # 2026-09-02 止盈禁买表
                        _blk, _why = cooldown.check_cooldown(_c3, code, 'main', price, score)
                        if not _blk:
                            # 2026-09-02 止盈禁买回（达目标价/回撤止盈卖出后，与名单无关；用户拍板）
                            _blk, _why = cooldown.check_tp_ban_signal(
                                _c3, code, 'main', cooldown.TP_REENTRY_BAN_DAYS)
                        _c3.close()
                    except Exception:
                        _blk, _why = False, ''
                    if _blk:
                        print(f"  🛡️ {code} {_why}（禁买期内不接回）")
                        continue
                    log_date = datetime.now().strftime('%Y-%m-%d')
                    sig_date = str(dmax)
                    if code in tail30:
                        print(f"  ⏭ {code} 昨日急拉 {tail30[code]*100:+.1f}% 且VWAP正偏 → 不追高（出货式拉升, 次日中位-1.32%）")
                        _log_tdx_signal(log_date, sig_date, code, 'excluded_tail', 'EXCLUDE', price)
                        continue
                    if code in tail5:
                        print(f"  ⏭ {code} 昨日最后5分钟急拉 {tail5[code]*100:+.1f}% → 不追高（尾盘突击诱多, 次日中位-1.23%, 5/5月为负）")
                        _log_tdx_signal(log_date, sig_date, code, 'excluded_tail5', 'EXCLUDE', price)
                        continue
                    if code in entrap:
                        print(f"  ⏭ {code} 诱多组合(开跌+VWAP高+振幅大) → 不买（次日中位-1.09%）")
                        _log_tdx_signal(log_date, sig_date, code, 'excluded_entrap', 'EXCLUDE', price)
                        continue
                    if code in low_absorb:
                        # 低吸确认: ①10:00 后（开盘30分钟定型）②现价 > 当日开盘价（开盘走强）
                        now = datetime.now()
                        if now.hour < 10:
                            print(f"  ⏭ {code} 低吸候选: 10:00 前等待开盘走强确认（昨日尾盘跌 {low_absorb[code]*100:+.1f}%）")
                            continue
                        open_p = get_live_open(code)
                        if not open_p or open_p <= 0 or price < open_p:
                            print(f"  ⏭ {code} 低吸候选: 开盘未走强(现价 {price} < 开盘 {open_p}), 当日不追")
                            continue
                        tags = []
                        if code in wash:
                            tags.append('资金洗盘')
                        if code in panic:
                            tags.append('恐慌出清')
                        tag = '+'.join(tags) if tags else '普通低吸'
                        print(f"  ✚ {code} 低吸确认[{tag}]: 现价 {price} > 开盘 {open_p}（昨日尾盘跌 {low_absorb[code]*100:+.1f}%）")
                        _log_tdx_signal(log_date, sig_date, code, 'wash' if code in wash else ('panic' if code in panic else 'low_absorb'), 'LOWABS_CONFIRM', price)
                    
                    # 高开观察（2026-08-08）: gap>3% → 次日偏强(+0.34%), 买入加分标记
                    gap_flag = ''
                    try:
                        o_p, p_p = get_live_open(code), get_live_prev(code)
                        if o_p and p_p and p_p > 0:
                            gap_pct = (o_p / p_p - 1) * 100
                            if gap_pct > 3:
                                gap_flag = f" [高开+{gap_pct:.1f}%]"
                    except Exception:
                        pass
                    
                    # 低吸候选跳过介入区间检查（2026-08-08 冲突修复: 低吸确认"10点后+开盘走强"已代替区间择时,
                    # 原 entry_low/entry_high 是信号日收盘附近区间, 开盘走强后现价必超 entry_high 会被误拦）
                    el, eh = (0, 0) if code in low_absorb else (entry_low, entry_high)
                    reason = check_buy_conditions(code, score, price, change, industry_counts, market_chg,
                                                     entry_low=el, entry_high=eh)
                    if reason != 'ok':
                        print(f"  ⏭ {code} 评分{score:.0f} {reason}")
                        continue
                    
                    # 多信号源交叉验证（标注模式，不设硬门槛）：
                    # - 三因子融合分 >= 85（强买档）或 CMMR > 0 的标注到 reason
                    f3_flag = ''
                    if f3_score >= 85:
                        f3_flag = ' [三因子强]'
                    elif f3_score >= 50:
                        f3_flag = f' [三因子{f3_score:.0f}]'
                    # 2026-09-11 用户拍板：[CMMRxx] 标注已移除（该标注会进交易明细 reason，CMMR 不再出现在任何推送）
                    
                    shares, label = get_position_sizing(cash, total_value, price, score, market_chg, code,
                                                        defense_mode=_dmode)
                    
                    if shares < 100:
                        print(f"  ⏭ {code} 仓位太小（现金{cash:,.0f}×{label} 买不起100股）")
                        continue
                    
                    signals.append({
                        'stock_code': code,
                        'action': 'BUY',
                        'shares': shares,
                        'price': price,
                        'reason': f'{label} 评分{score:.0f}{f3_flag}{gap_flag}',
                        'signal_score': score,
                        'target_price': target,
                        'stop_loss': stop_loss
                    })
                    bump_industry(industry_counts, code)  # L4: tick 内累加，防同 tick 连买同行业超限
                    print(f"  📈 {code} {label} 评分{score:.0f} → {shares}股")
                    # TDX 信号归因: 记录本次买入的信号类型（2026-08-08 用户要求）
                    _log_tdx_signal(log_date, sig_date, code,
                                    'wash' if code in low_absorb and code in wash else
                                    ('low_absorb' if code in low_absorb else 'normal_buy'),
                                    'BUY', price)
                    
                    # 只取评分最高的 1-2 只（2026-08-28 修复：原 len(signals) 含卖出信号——
                    # 卖出 2 只的日子买入配额被吃完。改用 buy_count 单独计数）
                    buy_count += 1
                    if buy_count >= 2:
                        break
    
    # ── 写入 pending.json ─────────────────────────────────────
    if signals:
        PENDING_FILE.parent.mkdir(exist_ok=True)
        output = {
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            'source_timestamp': now.strftime('%Y%m%d%H%M%S'),
            'market_change': market_chg,
            'signals': signals
        }
        PENDING_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"\n✅ 生成 {len(signals)} 条订单 → {PENDING_FILE}")
    else:
        # 清空 pending
        if PENDING_FILE.exists():
            PENDING_FILE.unlink()
        print(f"\n✓ 无新订单")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"⚠️ {e}")
        sys.exit(0)
