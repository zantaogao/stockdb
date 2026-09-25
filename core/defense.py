# -*- coding: utf-8 -*-
"""防御状态机（2026-09-16 用户拍板"挂上吧"，依据 DECISIONS.md 当日行）

mode（存 ledger.db defense_state 单行表，全系统唯一真源）：
  normal  —— 一切照常（表缺失=normal）
  halved  —— 第二层（议息鹰派/布油站稳107，明早人工核验后写入）：
             新开仓仓位×0.5；浮亏止损收紧 -5%；持仓 fusion<3 清出
  crash2  —— 第三层（自动升级）：昨日确认大跌市（中证1000 收盘跌幅≤-3%）
             且今日 14:30 后再收阴（实时<昨日收盘）→ 持仓按 fusion 升序
             整仓卖出，直到持仓市值≤NAV×50%

收复（对称，自动）：mode≠normal 且 中证1000 实时价 ≥ ref_close（激活时记的
破位前收盘，当前=2026-09-15 的 7437.7033）→ 回 normal，恢复满仓运作。
买点恢复另需非大跌市条件（既有 is_crash_market 管），本模块只管仓位/止损/清票口径。

回滚：`python3 -m core.defense reset` 删状态行=回 normal；代码回滚用两脚本的
.bak.20260916_defense 备份。
"""
import sqlite3
import os
import sys
from datetime import datetime

BASE = os.path.expanduser('~/.hermes/stockdb')
LEDGER = os.path.join(BASE, 'ledger.db')
SIGNALS = os.path.join(BASE, 'signals.db')
TUSHARE = os.path.join(BASE, 'tushare.db')

ZZ1000 = '000852'
HALVE_SCALE = 0.5           # 防守态新开仓折扣
DEFENSE_FUSION_FLOOR = 3.0  # 防守态持仓 fusion 低于此值清出
DEFENSE_FLOAT_STOP = 0.95   # 防守态浮亏止损收紧到 -5%
NORMAL_FLOAT_STOP = 0.94    # 正常态 -6%（R7 原值）
CRASH2_MV_CAP = 0.50        # crash2 持仓市值上限 = NAV×50%
CRASH2_KEEP = CRASH2_MV_CAP  # 同义别名（strategy_accounts_daily 用此名）
CRASH_CHG = -3.0            # 大跌日定义（与 CRASH_THRESHOLD 同口径）
CONFIRM_TIME = '14:30'      # 收盘判定时刻（盘中实时价≈收盘价）


def _conn():
    c = sqlite3.connect(LEDGER, timeout=15)
    c.execute("CREATE TABLE IF NOT EXISTS defense_state "
              "(mode TEXT PRIMARY KEY, ref_close REAL, set_date TEXT, note TEXT)")
    return c


def get_state():
    try:
        c = _conn()
        r = c.execute("SELECT mode, ref_close, note FROM defense_state LIMIT 1").fetchone()
        c.close()
        return (r[0], r[1], r[2] or '') if r else ('normal', None, '')
    except Exception:
        return ('normal', None, '')


def set_state(mode, ref_close=None, note=''):
    c = _conn()
    c.execute("DELETE FROM defense_state")
    if mode != 'normal':
        c.execute("INSERT INTO defense_state VALUES (?,?,?,?)",
                  (mode, ref_close, datetime.now().strftime('%Y-%m-%d %H:%M'), note))
    c.commit()
    c.close()


def buy_scale(mode):
    return HALVE_SCALE if mode in ('halved', 'crash2') else 1.0


def float_stop(mode):
    return DEFENSE_FLOAT_STOP if mode in ('halved', 'crash2') else NORMAL_FLOAT_STOP


def defense_kill_fusion(mode, fusion):
    """防守态下 fusion<3 → 清出（fusion 取不到 None 不误杀）"""
    return mode in ('halved', 'crash2') and fusion is not None and fusion < DEFENSE_FUSION_FLOOR


def get_fusion_map():
    """裸码 -> 最新信号日 fusion_score（signal_history，None 值跳过）"""
    try:
        c = sqlite3.connect(f"file:{SIGNALS}?mode=ro", uri=True, timeout=15)
        rows = c.execute("""
            SELECT stock_code, fusion_score FROM signal_history
            WHERE REPLACE(date,'-','') = (SELECT MAX(REPLACE(date,'-','')) FROM signal_history)
        """).fetchall()
        c.close()
        m = {}
        for code, f in rows:
            bare = code.split('.')[0][-6:] if '.' in code else code[-6:]
            if f is not None:
                m[bare] = f
        return m
    except Exception:
        return {}


def _index_last_two():
    """tushare.db index_daily_raw 最近两行 [(date, close, pct_chg)]（盘中含昨日收盘）"""
    try:
        import duckdb
        con = duckdb.connect(TUSHARE, read_only=True)  # ⚠️ 勿用 file: URI（本机 duckdb 会误找 file 扩展）
        rows = con.execute("""
            SELECT trade_date, close, pct_chg FROM index_daily_raw
            WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 2
        """).fetchall()
        con.close()
        return rows
    except Exception:
        return []


def evaluate(live_px, live_chg):
    """决策脚本每轮调用。live_px/live_chg = 中证1000 实时价/涨跌幅%。
    返回 (新mode, 事件说明或None)。拿不到实时价不改状态（保守）。
    升级 crash2：昨日大跌（DB 最新行 chg≤-3）且 14:30 后 实时价 < 昨收。
    收复：mode≠normal 且 实时价 ≥ ref_close。"""
    mode, ref, note = get_state()
    if not live_px or live_px <= 0:
        return mode, None
    now_ts = datetime.now().strftime('%H:%M:%S')
    # 收复
    if mode != 'normal' and ref and live_px >= ref:
        set_state('normal')
        return 'normal', f'收复破位前收盘{ref:.0f}(实时{live_px:.0f}) → 撤销防守({mode})'
    # 升级 crash2（只在 14:30 后判定，实时≈收盘）
    if mode in ('normal', 'halved') and now_ts >= CONFIRM_TIME:
        rows = _index_last_two()
        if rows:
            y_date, y_close, y_chg = rows[0]
            if y_chg is not None and y_chg <= CRASH_CHG and live_px < y_close:
                d_prev = rows[1][1] if len(rows) > 1 else y_close
                set_state('crash2', ref_close=d_prev,
                          note=f'大跌日{y_date}({y_chg:+.1f}%)次日再收阴')
                return 'crash2', (f'大跌市({y_date} {y_chg:+.2f}%)次日续跌(实时{live_px:.0f}'
                                  f'<昨收{y_close:.0f}) → 升级crash2，减至5成仓')
    return mode, None


def cut_plan(mode, positions, cash, fusion_map):
    """crash2 减仓清单：positions=[{code,shares,price}]，按 fusion 升序整仓卖
    直到剩余市值≤NAV×50%。fusion 缺失(None)不砍（模型没说话不动）。
    返回 (codes, 说明)；非 crash2 或已≤5成 返回 ([], '')。"""
    if mode != 'crash2':
        return [], ''
    mv = sum(p['shares'] * p['price'] for p in positions if p['price'])
    nav = mv + (cash or 0)
    if nav <= 0 or mv <= nav * CRASH2_MV_CAP:
        return [], ''
    cand = sorted((p for p in positions if fusion_map.get(p['code'][-6:]) is not None),
                  key=lambda p: fusion_map[p['code'][-6:]])
    to_cut, acc = [], 0.0
    for p in cand:
        if mv - acc <= nav * CRASH2_MV_CAP:
            break
        to_cut.append(p['code'])
        acc += p['shares'] * p['price']
    return to_cut, (f'crash2减至5成：NAV{nav/1e4:.0f}万 市值{mv/1e4:.0f}万>'
                    f'{CRASH2_MV_CAP*100:.0f}% → 卖fusion最低{len(to_cut)}只({acc/1e4:.0f}万)')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'show'
    if cmd == 'show':
        m, r, n = get_state()
        print(f'mode={m} ref_close={r} note={n}')
        rows = _index_last_two()
        print('index_daily_raw 最近两行:', rows)
    elif cmd == 'reset':
        set_state('normal')
        print('defense_state 已清空 → normal')
    elif cmd == 'halve' and len(sys.argv) > 2:
        ref = float(sys.argv[2])
        set_state('halved', ref_close=ref, note='09-16议息核验人工激活')
        print(f'set halved, ref_close={ref}')
    else:
        print(__doc__)
