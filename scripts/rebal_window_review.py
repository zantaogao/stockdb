#!/usr/bin/env python3
"""重评窗口 20 日复核（center_dual 中枢版+三模型，2026-09-11 切换后 30 成熟交易日复核用）

只读脚本：从 signals.db / ledger.db / tushare.db 聚合数据，输出表格给 LLM 解读。
切换背景：2026-09-11 用户拍板 center_dual 重评间隔 15 → 20 个交易日（证据为外推：
中枢腿 20–40 日 + 三模型腿 40 日预测窗同向；组合自身当时无独立证据）→ 约定 30 个
成熟交易日后复核，本脚本即复核的数据底稿。

用法：
  /usr/bin/python3 -B scripts/rebal_window_review.py            # 默认切换日 20260911
  /usr/bin/python3 -B scripts/rebal_window_review.py --cut 20260807   # 换切点（自测用）
禁止写库/改代码。
"""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import duckdb

BASE = Path(__file__).resolve().parent.parent
SIG = BASE / 'signals.db'
LED = BASE / 'ledger.db'
TDB = BASE / 'tushare.db'
SIG_START = '20260807'          # fusion_center 信号起点（08-06 上线，08-07 首日信号）
CUT = '20260911'                # 20 日窗口生效日
ACCT = 'center_dual'

if '--cut' in sys.argv:
    CUT = sys.argv[sys.argv.index('--cut') + 1]


def f(v, p='+.3f'):
    return '  n/a' if v is None else format(float(v), p)


def mean(seq):
    seq = [x for x in seq if x is not None]
    return float(np.mean(seq)) if seq else None


def main():
    print(f'===== 重评窗口 20 日复核底稿（切点 {CUT}，账户 {ACCT}）=====')
    tdu = duckdb.connect(str(TDB), read_only=True)
    tdays = [str(r[0]) for r in tdu.execute(
        "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
    post_td = [d for d in tdays if d > CUT]
    print(f'\n[1] 数据成熟度：切换后已完成交易日 {len(post_td)} 天'
          f'（{post_td[0] if post_td else "无"} ~ {post_td[-1] if post_td else "无"}）；'
          f'最新交易日 {tdays[-1]}')

    # ── 2. 组合（center_dual）IC 与窗口收益 ──
    sconn = sqlite3.connect(str(SIG), timeout=30)
    cols = [r[1] for r in sconn.execute('PRAGMA table_info(center_dual_ic_daily)').fetchall()]
    if cols:
        rows = sconn.execute(
            "SELECT date, ic, top_ret, fwd10_top10, fwd20_top10, fwd40_top10 "
            "FROM center_dual_ic_daily WHERE REPLACE(date,'-','') >= ? "
            "ORDER BY REPLACE(date,'-','')", (SIG_START,)).fetchall()
        groups = {'切换前(15日窗口)': [r for r in rows if str(r[0]).replace('-', '') < CUT],
                  '切换后(20日窗口)': [r for r in rows if str(r[0]).replace('-', '') >= CUT]}
        print('\n[2] 组合 center_dual 信号质量（0.5*pct(中枢) + 0.5*pct(三模型)）')
        print('| 组别 | 信号日数 | 次日IC均值 | IC>0占比 | top10次日超额% | fwd10 均值%(n) | fwd20 均值%(n) | fwd40 均值%(n) |')
        print('|---|---|---|---|---|---|---|---|')
        for g, rs in groups.items():
            ic = [r[1] for r in rs if r[1] is not None]
            top = [r[2] for r in rs if r[2] is not None]
            f10 = [r[3] for r in rs if r[3] is not None]
            f20 = [r[4] for r in rs if r[4] is not None]
            f40 = [r[5] for r in rs if r[5] is not None]
            pos = f'{sum(1 for x in ic if x > 0)}/{len(ic)}' if ic else 'n/a'
            print(f'| {g} | {len(rs)} | {f(mean(ic))} | {pos} | {f(mean(top))} | '
                  f'{f(mean(f10))}({len(f10)}) | {f(mean(f20))}({len(f20)}) | {f(mean(f40))}({len(f40)}) |')
        print('  说明：fwdX = 该信号日 top10 等权持有 X 个交易日的收益（%），n=已成熟样本数。')
    else:
        print('\n[2] center_dual_ic_daily 表不存在')

    # ── 3. 对照腿 ──
    print('\n[3] 对照腿（同期，切点同口径）')
    try:
        rows = sconn.execute(
            "SELECT date, ic FROM fusion_ic_daily WHERE REPLACE(date,'-','') >= ? ORDER BY 1",
            (SIG_START,)).fetchall()
        pre = [r[1] for r in rows if str(r[0]).replace('-', '') < CUT and r[1] is not None]
        post = [r[1] for r in rows if str(r[0]).replace('-', '') >= CUT and r[1] is not None]
        print(f'  三模型融合(逐日快照) 次日IC：切换前 {f(mean(pre))}(n={len(pre)}) / 切换后 {f(mean(post))}(n={len(post)})')
    except Exception as e:
        print('  fusion_ic_daily 读取失败:', e)
    try:
        rows = sconn.execute(
            "SELECT signal_date, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily "
            "WHERE REPLACE(signal_date,'-','') >= ? ORDER BY 1", (SIG_START,)).fetchall()
        for lbl, idx in (('10d', 1), ('20d', 2), ('40d', 3)):
            pre = [r[idx] for r in rows if str(r[0]).replace('-', '') < CUT and r[idx] is not None]
            post = [r[idx] for r in rows if str(r[0]).replace('-', '') >= CUT and r[idx] is not None]
            print(f'  三模型 {lbl} 次日IC：切换前 {f(mean(pre))}(n={len(pre)}) / 切换后 {f(mean(post))}(n={len(post)})')
    except Exception as e:
        print('  ic_daily 读取失败:', e)

    # ── 4. 实盘账户：持有期与换手 ──
    print(f'\n[4] 实盘账户 {ACCT}')
    try:
        lconn = sqlite3.connect(str(LED), timeout=30)
        import json
        cfg = lconn.execute("SELECT config_json FROM strategy_accounts_meta WHERE account_id=?",
                            (ACCT,)).fetchone()
        last_re = ''
        if cfg and cfg[0]:
            try:
                last_re = str(json.loads(cfg[0]).get('last_rebalance_date') or '')
            except Exception:
                last_re = '(解析失败)'
        print(f'  当前 last_rebalance_date = {last_re or "n/a"}')

        # 持仓与持有交易日
        try:
            pcols = [r[1] for r in lconn.execute('PRAGMA table_info(strategy_positions)').fetchall()]
            if pcols:
                prs = lconn.execute(
                    "SELECT code, shares, buy_date FROM strategy_positions WHERE account_id=?",
                    (ACCT,)).fetchall()
                tdidx = {d: i for i, d in enumerate(tdays)}
                hold = [tdidx[tdays[-1]] - tdidx[str(b).replace('-', '')]
                        for _, _, b in prs if str(b).replace('-', '') in tdidx]
                print(f'  持仓 {len(prs)} 只；持有交易日：均值 {f(mean(hold), "+.1f")} / 最长 {max(hold) if hold else "n/a"}')
        except Exception as e:
            print('  strategy_positions 读取失败:', e)

        # 换手：以切换日为界统计每交易日成交笔数与买入金额
        tr = lconn.execute(
            "SELECT trade_date, direction, amount FROM trade_log WHERE strategy=? "
            "AND REPLACE(trade_date,'-','') >= ? ORDER BY trade_date", (ACCT, SIG_START)).fetchall()
        for g, lo, hi in (('切换前', SIG_START, CUT), ('切换后', CUT, '99999999')):
            sub = [r for r in tr if lo <= str(r[0]).replace('-', '') < hi]
            ndays = len([d for d in tdays if lo <= d < hi])
            buys = sum(float(r[2] or 0) for r in sub if str(r[1]).upper().startswith('B'))
            print(f'  {g}：成交 {len(sub)} 笔 / {ndays} 交易日 = {len(sub)/ndays if ndays else 0:.1f} 笔/日；'
                  f'买入金额 {buys/1e4:.1f} 万元（{buys/(ndays*1e6)*100 if ndays else 0:.1f}% 初始资金/日 换手代理）')
    except Exception as e:
        print('  ledger.db 读取失败:', e)

    print('\n[5] 判读提示（给解读用，不是结论）')
    print('  - 20 日窗口的核心检验：切换后 fwd20 是否 ≥ fwd10（长窗口不吃亏）+ 换手是否下降。')
    print('  - 样本不足（fwd20 成熟样本 < 20 或切换后信号日 < 20）→ 只能说"待观察"，禁止硬下结论。')
    print('  - 口径红线：不得把中枢+三模型说成"40 日窗口"（40 日属三模型腿）；不得称中枢为 1–5 日窗口。')


if __name__ == '__main__':
    main()
