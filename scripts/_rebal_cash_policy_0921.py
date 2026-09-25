# -*- coding: utf-8 -*-
"""重评窗口「窗口内现金政策」17 年对比回测（2026-09-21，用户拍板"试试"）

背景（实盘）：
 中枢版 9/11 起 topup='gap'（窗口内不买新票，只补"在榜且已持有"），叠加窗口 10→20 日；
 实盘结果：持仓与名单脱节 → 现金一分钱补不进去 → 仓位 35%（现金 73 万）冻到下次重评，
 9/11→9/21 仅 +0.99% vs 市场 +4.50%（-3.51pp）。另外发现 gap 的 per_target 口径 bug：
 (cash + 仅"在榜的已持有票"市值)/10 → 掉榜即分母塌陷 → 旧版碎仓根因。

四口径（其余规则完全一致，仅"窗口内现金怎么用"不同）：
 A 现状 gap  ：不买新票；只补"在榜(=上次重评名单)且已持有"的票，目标=(cash+在榜持仓)/名单数  ← 现状
 B 固定名单  ：不跟随漂移；把"上次重评名单"里任一未持有/有缺口的票补到 NAV/名单数（★推荐候选）
 C 跟随漂移  ：把"当日信号 top10"补到 NAV/名单数（≈ 每天向最新名单再平衡，回到高换手）
 D 完全不补  ：卖出后现金全闲置（最坏上界，用于量化"现金拖累"）

窗口 R ∈ {10, 20}（9/11 拍板 20 的依据是"重评日满仓持有"口径，本回测补上"窗口内止损+现金"这一层）。

名单来源（可复现，刻意不用历史模型分——模型分有被训练覆盖的风险）：
 复刻生产 CMMR 口径（slope/pct10/量能三腿，权重 40/40/20，池>=0.8，池内 分降+pct10 升取前 10），
 与 scripts/_cmmr_weight_grid_17y_0920.py 逐字同源。

风控复刻 strategy_accounts_daily.py：
 R5 硬止损 -12%（-0.88）/ 加速 -9%（-0.91）/ R7 浮亏 -6%（-0.94，开盘破位或收盘确认）/
 R6 移动止盈（峰值>=成本*1.05 且收盘<=峰值*0.92）；止损/止盈卖出后 10 交易日冷却不买回。
成交：重评日 = 信号日次日开盘整仓重建；风控与补仓 = 当日收盘价。成本 0.1%/边。
停牌：价格 ffill（与 9/20 网格同口径）。

输出：全期/分年指标表（净收益、年化、最大回撤、平均仓位、交易笔数、换手）
"""
import os
import time

import duckdb
import numpy as np
import pandas as pd

HOME = os.path.expanduser('~')
DB = f'{HOME}/.hermes/stockdb/tushare.db'
SIG = f'{HOME}/.hermes/stockdb/signals.db'
OUTDIR = f'{HOME}/.hermes/stockdb/analysis'
START = os.environ.get('START_DATE', '20090101')
COST = 0.001          # 单边成本（佣金+印花+滑点合计口径，同 9/20 网格）
INIT = 1_000_000.0
COOL = 10             # 止损/止盈卖出后禁买回交易日
REBALS = [10, 20]
POLICY_DESC = {
    'A': '现状gap(只补在榜已持有, 目标=(cash+在榜)/N)',
    'B': '固定名单补NAV/N(上次重评名单全补)',
    'C': '跟随漂移补NAV/N(当日top10)',
    'D': '完全不补(现金全闲置)',
    'E': '满仓持有(无风控/无补仓；= 9/20 网格的"重评日满仓持有"口径，用于分离止损影响)',
}

t0 = time.time()
os.makedirs(OUTDIR, exist_ok=True)
con = duckdb.connect(DB, read_only=True)
con.execute("SET memory_limit='24GB'")
bad = set()
sc = __import__('sqlite3').connect(f'file:{SIG}?mode=ro', uri=True)
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8', '4', '92')):
        bad.add(str(code))
sc.close()
print(f'ST/退市/北交所剔除: {len(bad)}', flush=True)

df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) AS td, d."open", d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date >= '{START}'
""").df()
print(f'rows: {len(df)}  {time.time()-t0:.0f}s', flush=True)
con.close()
df = df[~df.ts_code.str[:6].isin(bad)]

col_order = sorted(df.ts_code.unique())
C_INDEX = {c: j for j, c in enumerate(col_order)}


def piv(col):
    return (df.pivot(index='td', columns='ts_code', values=col)
              .reindex(columns=col_order).astype('float32'))


close = piv('close')
opn = piv('open')
vol = piv('vol')
adjf = piv('adj_factor').ffill().fillna(1.0)
A = (close * adjf)                      # 复权收盘（价格比例正确）
AO = (opn * adjf)                       # 复权开盘
A_ff = A.ffill().values
AO_ff = AO.ffill().values
cal = list(close.index)
n = len(cal)
print(f'cal: {n}  {cal[0]} -> {cal[-1]}  {time.time()-t0:.0f}s', flush=True)

# ── 因子矩阵（与生产 CMMR 逐字同口径）──
ma40 = close.rolling(40).mean()
ma40_prev = close.rolling(20).mean().shift(40)
slope = ((ma40 - ma40_prev) / ma40_prev).values
p10 = (close / close.shift(10) - 1).values
vr = (vol / vol.rolling(5).mean()).values
enough = (close.rolling(60).count().values >= 60)
S, P = slope, p10
R_ = vr
O_, C_ = opn.values, close.values
T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0)).astype('float32')
Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0)).astype('float32')
V = np.where((R_ < 0.8) | ((R_ > 1.2) & (C_ > O_)), 1.0, 0.0).astype('float32')
kill = (S < 0) | ~enough | np.isnan(C_)
T[kill] = 0
Ov[kill] = 0
V[kill] = 0
SCORE = (40 * T + 40 * Ov + 20 * V) / 100.0
print(f'因子矩阵就绪 {time.time()-t0:.0f}s', flush=True)

# ── 每日名单（信号日 i 的 top10，i+1 开盘买入）──
NAMES = {}
for i in range(60, n - 1):
    srow = SCORE[i]
    pool = np.where(srow >= 0.8)[0]
    if len(pool) < 10:
        continue
    ps, pp = srow[pool], P[i, pool]
    ok = ~np.isnan(pp)
    ps, pp = ps[ok], pp[ok]
    if len(ps) < 10:
        continue
    order = np.lexsort((pp, -ps))[:10]
    NAMES[i] = [col_order[j] for j in pool[ok][order]]
print(f'有效信号日 {len(NAMES)}  {time.time()-t0:.0f}s', flush=True)


def simulate(R, policy):
    """返回 (nav 序列, 指标 dict)"""
    rebal_idx = [i for i in sorted(NAMES) if (i - 60) % R == 0]
    rebal_set = set(rebal_idx)
    cur_list = None          # 上次重评名单（口径 A/B 用）
    pending_rebal = False    # 次日开盘执行重建
    cash = INIT
    pos = {}                 # code -> [shares, cost, peak]
    cool_until = {}
    nav_hist = []
    trades = 0
    expo_sum = 0.0
    fee_sum = 0.0

    def buy(code, budget, px):
        nonlocal cash, trades, fee_sum
        if px is None or px <= 0 or np.isnan(px):
            return
        shares = int(budget / px / 100) * 100
        if shares < 100:
            return
        if code[:2] in ('30', '68') and shares < 200:
            return
        amt = shares * px
        if amt > cash:
            return
        cash -= amt + amt * COST
        fee_sum += amt * COST
        trades += 1
        if code in pos:
            old_sh, old_cost = pos[code][0], pos[code][1]
            new_sh = old_sh + shares
            pos[code] = [new_sh, (old_cost * old_sh + px * shares) / new_sh, pos[code][2]]
        else:
            pos[code] = [shares, px, px]

    def sell(code, px):
        nonlocal cash, trades, fee_sum
        if code not in pos:
            return
        sh = pos[code][0]
        amt = sh * px
        cash += amt - amt * COST
        fee_sum += amt * COST
        trades += 1
        pos.pop(code)

    for i in range(60, n):
        # ① 次日开盘：执行重评重建（全部卖出 + 等权买入新名单）
        if pending_rebal:
            for code in list(pos.keys()):
                sell(code, AO_ff[i, C_INDEX[code]])
            tgt = NAMES.get(i - 1)
            if tgt:
                for code in tgt:
                    buy(code, cash / len(tgt), AO_ff[i, C_INDEX[code]])
            pending_rebal = False

        # ② 风控（每日收盘；开盘破位用开盘价）—— 与实盘 R5/R6/R7 同口径
        #    口径 E 例外：满仓持有、不做任何风控（= 9/20 网格口径）
        for code in ([] if policy == 'E' else list(pos.keys())):
            j = C_INDEX[code]
            o, c = AO_ff[i, j], A_ff[i, j]
            if np.isnan(o) or np.isnan(c):
                continue
            sh, cost, peak = pos[code]
            peak = max(peak, c)
            px = None
            if o <= cost * 0.88:
                px = o
            elif o <= cost * 0.94:
                px = o
            elif c <= cost * 0.88:
                px = c
            elif c <= cost * 0.91:
                px = c
            elif c <= cost * 0.94:
                px = c
            elif peak >= cost * 1.05 and c <= peak * 0.92:
                px = c
            if px is not None:
                sell(code, px)
                cool_until[code] = i + COOL
            else:
                pos[code][2] = peak

        # ③ 窗口内现金政策（非重评日；重评日由 ① 处理）
        if policy in ('A', 'B', 'C') and i not in rebal_set:
            if policy == 'A':
                lst = cur_list or []
                held_val = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in lst if c in pos)
                per = (cash + held_val) / len(lst) if lst else 0.0
                cand = [c for c in lst if c in pos]
            elif policy == 'B':
                lst = cur_list or []
                mv = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in pos)
                per = (cash + mv) / len(lst) if lst else 0.0
                cand = list(lst)
            else:  # C：跟随当日名单（用 i-1 信号日名单，避免 look-ahead：i 日收盘时已知的最近名单）
                lst = NAMES.get(i - 1, [])
                mv = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in pos)
                per = (cash + mv) / len(lst) if lst else 0.0
                cand = list(lst)
            if per > 5000:
                need = []
                for c in cand:
                    j = C_INDEX[c]
                    cpx = A_ff[i, j]
                    if np.isnan(cpx) or cpx <= 0:
                        continue
                    if cool_until.get(c, -1) > i:
                        continue
                    have = pos[c][0] * cpx if c in pos else 0.0
                    gap = per - have
                    if gap >= 5000:
                        # R2 不追高 7%（对比昨收）
                        prev = A_ff[i - 1, j]
                        if not np.isnan(prev) and prev > 0 and cpx / prev - 1 >= 0.07:
                            continue
                        # R7 浮亏 ≤-6% 不加仓
                        if c in pos and cpx <= pos[c][1] * 0.94:
                            continue
                        need.append((gap, c, cpx))
                for gap, c, cpx in sorted(need, reverse=True):
                    if cash < 5000:
                        break
                    buy(c, min(gap, cash), cpx)

        # ④ 重评日收盘：标记次日开盘重建
        if i in rebal_set and i + 1 < n:
            cur_list = NAMES.get(i, cur_list)
            pending_rebal = True

        mv = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in pos
                 if not np.isnan(A_ff[i, C_INDEX[c]]))
        nav = cash + mv
        nav_hist.append(nav)
        expo_sum += (mv / nav if nav > 0 else 0.0)

    navs = np.array(nav_hist)
    ret = navs[-1] / INIT - 1
    yrs = len(navs) / 243.0
    ann = (1 + ret) ** (1 / yrs) - 1
    peak = np.maximum.accumulate(navs)
    mdd = float((navs / peak - 1).min())
    expo = expo_sum / len(navs)
    # 分年
    ylabels = [str(d // 100) for d in cal[60:]]
    s = pd.Series(navs, index=ylabels)
    yr = s.groupby(level=0).last() / s.groupby(level=0).first() - 1
    return navs, dict(ret=ret, ann=ann, mdd=mdd, expo=expo, trades=trades,
                      fees=fee_sum, yr=yr, years=ylabels)


print('\n' + '=' * 118, flush=True)
print('窗口内现金政策 17 年对比（名单=CMMR40/40/20 top10；风控=R5/R6/R7 复刻；成本 0.1%/边）')
print('=' * 118, flush=True)
all_nav, all_met = {}, {}
for R in REBALS:
    for pol in ('A', 'B', 'C', 'D', 'E'):
        navs, met = simulate(R, pol)
        all_nav[(R, pol)] = navs
        all_met[(R, pol)] = met
        print(f'  R={R} 口径 {pol} 完成  NAV {navs[-1]:,.0f}  收益 {met["ret"]*100:+.1f}%  '
              f'年化 {met["ann"]*100:+.2f}%  仓位均 {met["expo"]*100:.0f}%  '
              f'回撤 {met["mdd"]*100:.1f}%  笔数 {met["trades"]}  {time.time()-t0:.0f}s', flush=True)

# ── 市场基准：全市场等权买入持有（逐日横截面中位收益累乘，与本回测同成本口径=零佣金）──
_prev = np.where(A_ff[:-1] > 0, A_ff[:-1], np.nan)
_r = np.where(np.isnan(A_ff[1:]) | np.isnan(_prev), np.nan, A_ff[1:] / _prev - 1)
mkt_ret = np.nan_to_num(np.nanmedian(_r, axis=1), nan=0.0)
mkt_nav = np.concatenate([[INIT], INIT * np.cumprod(1 + mkt_ret)])[60:]
_mk_peak = np.maximum.accumulate(mkt_nav)
MKT = dict(ret=float(mkt_nav[-1] / INIT - 1),
           ann=float((mkt_nav[-1] / INIT) ** (243.0 / len(mkt_nav)) - 1),
           mdd=float((mkt_nav / _mk_peak - 1).min()))
print(f'\n市场基准(全市场等权买入持有): 收益 {MKT["ret"]*100:+.1f}%  年化 {MKT["ann"]*100:+.2f}%  回撤 {MKT["mdd"]*100:.1f}%')

print('\n' + '=' * 118)
print('【表一】全期指标')
print('=' * 118)
hdr = f"{'R':>3} {'口径':>4} {'净收益%':>10} {'年化%':>8} {'最大回撤%':>10} {'平均仓位%':>10} {'交易笔数':>9} {'费用(万)':>9}  说明"
print(hdr)
for R in REBALS:
    for pol in ('A', 'B', 'C', 'D', 'E'):
        m = all_met[(R, pol)]
        print(f"{R:>3} {pol:>4} {m['ret']*100:>+10.1f} {m['ann']*100:>+8.2f} {m['mdd']*100:>10.1f} "
              f"{m['expo']*100:>10.1f} {m['trades']:>9} {m['fees']/1e4:>9.1f}  {POLICY_DESC[pol]}")
print(f"{'—':>3} {'MKT':>4} {MKT['ret']*100:>+10.1f} {MKT['ann']*100:>+8.2f} {MKT['mdd']*100:>10.1f} "
      f"{100.0:>10.1f} {0:>9} {0.0:>9.1f}  全市场等权买入持有（基准）")

print('\n' + '=' * 118)
print('【表二】分年净收益（%）')
print('=' * 118)
yrs_lbl = sorted(set(all_met[(20, 'A')]['yr'].index))
print(f"{'年':<6}" + ''.join([f"{'R' + str(R) + pol:>10}" for R in REBALS for pol in ('A', 'B', 'C', 'D', 'E')]))
for y in yrs_lbl:
    row = f"{y:<6}"
    for R in REBALS:
        for pol in ('A', 'B', 'C', 'D', 'E'):
            v = all_met[(R, pol)]['yr'].get(y, np.nan)
            row += f"{v*100:>+10.1f}" if not np.isnan(v) else f"{'—':>10}"
    print(row)
print(f"{'正年数':<6}" + ''.join([f"{int((all_met[(R,pol)]['yr']>0).sum()):>7}/{len(all_met[(R,pol)]['yr']):<3}"
                                 for R in REBALS for pol in ('A', 'B', 'C', 'D', 'E')]))

pd.DataFrame({f'R{R}_{pol}': all_nav[(R, pol)] for R in REBALS for pol in ('A', 'B', 'C', 'D', 'E')},
             index=[str(d) for d in cal[60:]]).to_csv(f'{OUTDIR}/rebal_cash_policy_0921_nav.csv')
print(f'\nNAV 明细已存 {OUTDIR}/rebal_cash_policy_0921_nav.csv  {time.time()-t0:.0f}s')
