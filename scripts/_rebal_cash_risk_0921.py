# -*- coding: utf-8 -*-
"""窗口内现金政策 × 风控档位 17 年对比回测 v2（2026-09-21）

v1 发现：基准用横截面中位数 → 全市场等权 17 年 -99.9%（荒谬）；A 股收益右偏，
"中位数"远低于"均值"，而等权组合的真实收益是**均值**。v2 改为均值（并保留中位数对照），
同时把"风控档位"参数化（分离止损规则的影响）——这正是 9/25 止损梯级复核需要的证据。

两个维度：
 现金政策（窗口内卖出释放的现金怎么用）：
   A 现状 gap ：只补"在榜(上次重评名单)且已持有"，目标=(cash+在榜持仓)/N   ← 实盘现状
   B 固定名单 ：把上次重评名单里所有缺口补到 NAV/N（不跟随漂移）
   C 跟随漂移 ：把当日信号 top10 补到 NAV/N
   D 完全不补 ：卖出后现金全闲置
 风控档位（复刻 strategy_accounts_daily.py 的 R5/R6/R7/R6止盈）：
   none   无风控（= 9/20 网格的"重评日满仓持有"口径）
   hard12 仅硬止损 -12%
   ha     -12% + 加速 -9%
   nofloat -12% + -9% + 移动止盈（不含 -6% 浮亏止损）
   full   -12% + -9% + -6% + 移动止盈  ← 实盘现状
   tp_only 仅移动止盈
窗口 R ∈ {10, 20}。名单可切换（LIST_FILE 环境变量）：
  未设 = CMMR 40/40/20 top10（负 alpha，仅作口径对照）
  设了 = 中枢版 top10 parquet（生产口径、17 年可复现、正 alpha）
  —— 2026-09-21 新增：回答"窗口内现金政策该不该改"必须在正 alpha 的生产名单上测；
     在负 alpha 名单上"买得越多亏得越多"是必然，测不出政策优劣（v1 的教训）。
成交：重评日=信号日次日开盘整仓重建；风控/补仓=当日收盘价。成本 0.1%/边。
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
LIST_FILE = os.environ.get('LIST_FILE', '')   # 中枢版名单 parquet（列 date,rank,ts_code,score）
TAG = os.environ.get('TAG', 'cmmr')           # 产出文件名标识
COST = 0.001
INIT = 1_000_000.0
COOL = 10
REBALS = [10, 20]
POLICIES = ['A', 'B', 'C', 'D']
RISKS = ['none', 'hard12', 'ha', 'nofloat', 'full', 'tp_only']
# (hard12, accel9, float6, take_profit)
RFLAG = {
    'none': (0, 0, 0, 0),
    'hard12': (1, 0, 0, 0),
    'ha': (1, 1, 0, 0),
    'nofloat': (1, 1, 0, 1),
    'full': (1, 1, 1, 1),
    'tp_only': (0, 0, 0, 1),
}
RISK_DESC = {
    'none': '无风控(满仓持有=9/20网格口径)',
    'hard12': '仅硬止损-12%',
    'ha': '-12%+加速-9%',
    'nofloat': '-12%+-9%+移动止盈(无-6%)',
    'full': '全套(-12/-9/-6+移动止盈)=实盘现状',
    'tp_only': '仅移动止盈',
}
POL_DESC = {
    'A': '现状gap(只补在榜已持有)',
    'B': '固定名单补NAV/N',
    'C': '跟随漂移补NAV/N',
    'D': '完全不补(现金闲置)',
}

t0 = time.time()
os.makedirs(OUTDIR, exist_ok=True)
con = duckdb.connect(DB, read_only=True)
con.execute("SET memory_limit='24GB'")
bad = set()
import sqlite3
sc = sqlite3.connect(f'file:{SIG}?mode=ro', uri=True)
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8', '4', '92')):
        bad.add(str(code))
sc.close()

df = con.execute(f"""
  SELECT d.ts_code, CAST(d.trade_date AS INT) AS td, d."open", d.close, d.vol, a.adj_factor
  FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
  WHERE d.trade_date >= '{START}'
""").df()
idx_df = con.execute("""
  SELECT ts_code, CAST(REPLACE(trade_date,'-','') AS INT) AS td, close FROM index_daily_raw
  WHERE ts_code IN ('000001.SH','000852.SH') ORDER BY td
""").df()
con.close()
print(f'rows {len(df)}  {time.time()-t0:.0f}s', flush=True)
df = df[~df.ts_code.str[:6].isin(bad)]
col_order = sorted(df.ts_code.unique())
C_INDEX = {c: j for j, c in enumerate(col_order)}


def piv(col):
    return (df.pivot(index='td', columns='ts_code', values=col)
              .reindex(columns=col_order).astype('float32'))


close = piv('close')
opn = piv('open')
vol = piv('vol')
# ⚠️ 2026-09-21 修复（v1 事故）：adj_factor 前端缺失若 fillna(1.0) 会让复权价在该日跳变
#   （close×1 → close×50）→ 单日"收益"几千 %，把均值基准拉成 +14161%（荒谬）。
#   修法：① 去掉 fillna(1.0)，前端保持 NaN（该票早期视为不可交易）；
#        ② 单日复权收益 |r| > 21%（超过创业板 20% 涨停上限）视为数据异常 → 该日价无效、
#           用上一有效价（等价收益 0）——正常交易日绝不会有这种幅度，只会命中数据缺口。
adjf = piv('adj_factor').ffill()
_rw = (close * adjf).values
_rr = np.zeros_like(_rw)
_rr[1:] = np.where((_rw[:-1] > 0) & (np.nan_to_num(_rw[:-1], nan=-1) > 0),
                   _rw[1:] / np.where(_rw[:-1] > 0, _rw[:-1], np.nan) - 1, np.nan)
_bad = np.abs(np.nan_to_num(_rr, nan=0.0)) > 0.21
print(f'异常日收益样本(|r|>21%，判为数据缺口): {int(_bad.sum()):,} / {_bad.size:,} '
      f'({_bad.sum()/max(_bad.size,1)*100:.4f}%)', flush=True)
A_ff = pd.DataFrame(np.where(_bad, np.nan, _rw), index=close.index).ffill().values
AO_ff = pd.DataFrame(np.where(_bad, np.nan, (opn * adjf).values),
                     index=close.index).ffill().values
cal = list(close.index)
n = len(cal)
print(f'cal {n}  {cal[0]}->{cal[-1]}  {time.time()-t0:.0f}s', flush=True)

ma40 = close.rolling(40).mean()
ma40_prev = close.rolling(20).mean().shift(40)
S = ((ma40 - ma40_prev) / ma40_prev).values
P = (close / close.shift(10) - 1).values
R_ = (vol / vol.rolling(5).mean()).values
enough = (close.rolling(60).count().values >= 60)
O_, C_ = opn.values, close.values
T = np.where(S > 0.02, 1.0, np.where(S > 0, 0.5, 0.0)).astype('float32')
Ov = np.where(P < -0.08, 1.0, np.where(P < -0.04, 0.5, 0.0)).astype('float32')
V = np.where((R_ < 0.8) | ((R_ > 1.2) & (C_ > O_)), 1.0, 0.0).astype('float32')
kill = (S < 0) | ~enough | np.isnan(C_)
T[kill] = 0
Ov[kill] = 0
V[kill] = 0
SCORE = (40 * T + 40 * Ov + 20 * V) / 100.0

NAMES = {}
if LIST_FILE:
    # 中枢版名单（生产口径，2026-09-21）：直接读 17 年逐日 top10 parquet
    #   parquet 列：date(YYYYMMDD str) | rank(1..10) | ts_code | score
    _T = pd.read_parquet(LIST_FILE)
    _by = {}
    for _d, _sub in _T.groupby('date'):
        _by[str(_d)] = list(_sub.sort_values('rank')['ts_code'])
    _dropped = 0
    for i in range(60, n - 1):
        # ⚠️ 2026-09-21 实撞：名单（tushare stock_basic 口径：只剔 ST/北交所/8/4）里可能含
        #    signals.db 口径额外剔除的票（名字带"退"、92 开头等）→ 不在 C_INDEX 里。
        #    必须在此过滤到回测的可交易票集合，否则 simulate() 建仓时 C_INDEX[code] 会 KeyError。
        _raw = _by.get(str(cal[i]), [])
        _lst = [c for c in _raw if c in C_INDEX]
        _dropped += len(_raw) - len(_lst)
        if _lst:
            NAMES[i] = _lst
    print(f'名单装载：命中信号日 {len(NAMES):,}，剔除不可交易票 {_dropped} 只·日  '
          f'({time.time()-t0:.0f}s)', flush=True)
else:
    for i in range(60, n - 1):   # CMMR 口径（口径对照用）
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
    print(f'信号日 {len(NAMES)}  {time.time()-t0:.0f}s', flush=True)


def simulate(R, policy, risk):
    reg = [i for i in sorted(NAMES) if (i - 60) % R == 0]
    reg_set = set(reg)
    cur_list, pending = None, False
    cash, pos, cool_until = INIT, {}, {}
    nav_hist, trades, fee_sum, expo_sum = [], 0, 0.0, 0.0
    hard, accel, f6, tp = RFLAG[risk]

    def buy(code, budget, px):
        nonlocal cash, trades, fee_sum
        if px is None or np.isnan(px) or px <= 0:
            return
        shares = int(budget / px / 100) * 100
        if shares < 100 or (code[:2] in ('30', '68') and shares < 200):
            return
        amt = shares * px
        if amt > cash:
            return
        cash -= amt * (1 + COST)
        fee_sum += amt * COST
        trades += 1
        if code in pos:
            os_, oc, pk = pos[code]
            ns = os_ + shares
            pos[code] = [ns, (oc * os_ + px * shares) / ns, pk]
        else:
            pos[code] = [shares, px, px]

    def sell(code, px):
        nonlocal cash, trades, fee_sum
        if code not in pos:
            return
        amt = pos[code][0] * px
        cash += amt * (1 - COST)
        fee_sum += amt * COST
        trades += 1
        pos.pop(code)

    for i in range(60, n):
        if pending:
            for code in list(pos.keys()):
                sell(code, AO_ff[i, C_INDEX[code]])
            tgt = NAMES.get(i - 1)
            if tgt:
                for code in tgt:
                    buy(code, cash / len(tgt), AO_ff[i, C_INDEX[code]])
            pending = False

        if risk != 'none':
            for code in list(pos.keys()):
                j = C_INDEX[code]
                o, c = AO_ff[i, j], A_ff[i, j]
                if np.isnan(o) or np.isnan(c):
                    continue
                sh, cost, peak = pos[code]
                peak = max(peak, c)
                px = None
                if hard and o <= cost * 0.88:
                    px = o
                elif f6 and o <= cost * 0.94:
                    px = o
                elif hard and c <= cost * 0.88:
                    px = c
                elif accel and c <= cost * 0.91:
                    px = c
                elif f6 and c <= cost * 0.94:
                    px = c
                elif tp and peak >= cost * 1.05 and c <= peak * 0.92:
                    px = c
                if px is not None:
                    sell(code, px)
                    cool_until[code] = i + COOL
                else:
                    pos[code][2] = peak

        if policy != 'D' and i not in reg_set:
            if policy == 'A':
                lst = cur_list or []
                hv = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in lst if c in pos)
                per = (cash + hv) / len(lst) if lst else 0.0
                cand = [c for c in lst if c in pos]
            elif policy == 'B':
                lst = cur_list or []
                mv = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in pos)
                per = (cash + mv) / len(lst) if lst else 0.0
                cand = list(lst)
            else:
                lst = NAMES.get(i - 1, [])
                mv = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in pos)
                per = (cash + mv) / len(lst) if lst else 0.0
                cand = list(lst)
            if per > 5000:
                need = []
                for c in cand:
                    j = C_INDEX[c]
                    cpx = A_ff[i, j]
                    if np.isnan(cpx) or cpx <= 0 or cool_until.get(c, -1) > i:
                        continue
                    have = pos[c][0] * cpx if c in pos else 0.0
                    gap = per - have
                    if gap < 5000:
                        continue
                    prev = A_ff[i - 1, j]
                    if not np.isnan(prev) and prev > 0 and cpx / prev - 1 >= 0.07:
                        continue
                    if c in pos and cpx <= pos[c][1] * 0.94:
                        continue
                    need.append((gap, c, cpx))
                for gap, c, cpx in sorted(need, reverse=True):
                    if cash < 5000:
                        break
                    buy(c, min(gap, cash), cpx)

        if i in reg_set and i + 1 < n:
            cur_list = NAMES.get(i, cur_list)
            pending = True

        mv = sum(pos[c][0] * A_ff[i, C_INDEX[c]] for c in pos
                 if not np.isnan(A_ff[i, C_INDEX[c]]))
        nav = cash + mv
        nav_hist.append(nav)
        expo_sum += (mv / nav if nav > 0 else 0.0)

    navs = np.array(nav_hist)
    ret = navs[-1] / INIT - 1
    ann = (1 + ret) ** (243.0 / len(navs)) - 1
    peak = np.maximum.accumulate(navs)
    mdd = float((navs / peak - 1).min())
    yl = [str(d // 10000) for d in cal[60:]]
    s = pd.Series(navs, index=yl)
    yr = s.groupby(level=0).last() / s.groupby(level=0).first() - 1
    return dict(ret=ret, ann=ann, mdd=mdd, expo=expo_sum / len(navs),
                trades=trades, fees=fee_sum, yr=yr)


# ── 基准：全市场等权（均值=真实等权收益；中位数=9/20 网格用的口径，作对照）──
CA = A_ff[60:]
_prev = np.where(CA[:-1] > 0, CA[:-1], np.nan)
_rr = np.where(np.isnan(CA[1:]) | np.isnan(_prev), np.nan, CA[1:] / _prev - 1)
_mean = np.nan_to_num(np.nanmean(_rr, axis=1), nan=0.0)
_med = np.nan_to_num(np.nanmedian(_rr, axis=1), nan=0.0)
nav_mean = INIT * np.cumprod(1 + _mean)
nav_med = INIT * np.cumprod(1 + _med)
yl_all = [str(d // 10000) for d in cal[61:]]
yr_mean = (pd.Series(nav_mean, index=yl_all).groupby(level=0).last()
           / pd.Series(nav_mean, index=yl_all).groupby(level=0).first() - 1)
print(f"\n市场基准 等权均值: 17y {nav_mean[-1]/INIT-1:+.1%}  年化 {(nav_mean[-1]/INIT)**(243/len(nav_mean))-1:+.2%}"
      f"   | 中位数(9/20 网格口径): {nav_med[-1]/INIT-1:+.1%}", flush=True)
for tsc, tag in (('000001.SH', '上证'), ('000852.SH', '中证1000')):
    sub = idx_df[(idx_df.ts_code == tsc) & (idx_df.td >= cal[60])].sort_values('td')
    if len(sub) > 100:
        print(f'  {tag}({tsc}) 同期: {sub.close.iloc[-1]/sub.close.iloc[0]-1:+.1%}'
              f'  ({sub.td.iloc[0]}→{sub.td.iloc[-1]})')

RES = {}
print('\n' + '=' * 112, flush=True)
print(f'窗口内现金政策 × 风控档位（17 年，名单={LIST_FILE or "CMMR40/40/20 top10"}，成本 0.1%/边）', flush=True)
print('=' * 112, flush=True)
for R in REBALS:
    for risk in RISKS:
        for pol in POLICIES:
            RES[(R, risk, pol)] = simulate(R, pol, risk)
        m = RES[(R, risk, 'A')]
        print(f"  R={R} 风控={risk:<8} 政策A: 收益 {m['ret']*100:+7.1f}%  年化 {m['ann']*100:+6.2f}%  "
              f"仓位 {m['expo']*100:4.0f}%  回撤 {m['mdd']*100:6.1f}%  {time.time()-t0:.0f}s", flush=True)


def line(R, risk, pol):
    m = RES[(R, risk, pol)]
    return (f"{R:>3} {risk:>8} {pol:>3} {m['ret']*100:>+10.1f} {m['ann']*100:>+8.2f} "
            f"{m['mdd']*100:>10.1f} {m['expo']*100:>10.1f} {m['trades']:>8} {m['fees']/1e4:>8.1f}")


print('\n' + '=' * 112)
print('【表一】风控档位分解（现金政策固定=A 实盘现状）')
print('=' * 112)
print(f"{'R':>3} {'风控':>8} {'政策':>3} {'净收益%':>10} {'年化%':>8} {'最大回撤%':>10} {'平均仓位%':>10} {'笔数':>8} {'费用万':>8}  说明")
for R in REBALS:
    for risk in RISKS:
        print(line(R, risk, 'A') + f"  {RISK_DESC[risk]}")
print(f"\n  基准: 等权均值 17y {nav_mean[-1]/INIT-1:+.1%}（年化 {(nav_mean[-1]/INIT)**(243/len(nav_mean))-1:+.2%}）"
      f" | 中位数口径 {nav_med[-1]/INIT-1:+.1%}")

print('\n' + '=' * 112)
print('【表二】现金政策对比（在实盘风控 full 下）')
print('=' * 112)
for R in REBALS:
    for pol in POLICIES:
        print(line(R, 'full', pol) + f"  {POL_DESC[pol]}")

print('\n' + '=' * 112)
print('【表三】分年净收益（%，关键组合）')
print('=' * 112)
KEYS = [(20, 'full', 'A'), (20, 'full', 'C'), (20, 'nofloat', 'A'), (20, 'hard12', 'A'), (20, 'none', 'A'),
        (10, 'full', 'A'), (10, 'none', 'A')]
years = sorted(set(RES[(20, 'full', 'A')]['yr'].index))
print(f"{'年':<6}" + ''.join([f"{f'R{r}{k}{p}':>12}" for r, k, p in KEYS]) + f"{'等权均值':>10}")
for y in years:
    row = f"{y:<6}"
    for r, k, p in KEYS:
        v = RES[(r, k, p)]['yr'].get(y, np.nan)
        row += f"{v*100:>+12.1f}" if not np.isnan(v) else f"{'—':>12}"
    vm = yr_mean.get(y, np.nan)
    row += f"{vm*100:>+10.1f}" if not np.isnan(vm) else f"{'—':>10}"
    print(row)
print(f"{'正年数':<6}" + ''.join([f"{int((RES[(r,k,p)]['yr']>0).sum()):>8}/{len(RES[(r,k,p)]['yr']):<4}" for r, k, p in KEYS])
      + f"{int((yr_mean>0).sum()):>7}/{len(yr_mean):<3}")

pd.DataFrame({f'R{R}_{k}_{p}': pd.Series(RES[(R, k, p)]['yr']).reindex(years)
              for R in REBALS for k in RISKS for p in POLICIES}).to_csv(f'{OUTDIR}/rebal_cash_{TAG}_year.csv')
print(f'\n分年明细 → {OUTDIR}/rebal_cash_{TAG}_year.csv   {time.time()-t0:.0f}s')
