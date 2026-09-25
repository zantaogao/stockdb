#!/usr/bin/env python3
"""四榜挑选：三模型融合 / CMMR+ / 中枢版 / 中枢版+三模型 → 建议买入清单

规则（08-27 定案，数据支撑见 top10 区分度回测）：
  1. 每榜取 top10（各自信号口径与 strategy_accounts_daily 一致）
  2. R2 追高过滤：今日涨幅 ≥ --r2% 排除（默认 7，涨停必排除）
  3. 榜间按权重分配资金（默认 CMMR+ 0.40 / 三模型 0.30 / 中枢版 0.20 / 中枢+三模型 0.10，
     按历史实盘强度排序；可用 --weights 覆盖）
  4. 榜内等权（回测证明榜内排名无区分度）
  5. 行业分散警告：同行业 > 3 只提示

用法：
  python3 scripts/pick_four_lists.py                  # 最新信号日
  python3 scripts/pick_four_lists.py --date 20260827  # 指定信号日
  python3 scripts/pick_four_lists.py --weights cmmr_plus:0.5,fusion3m:0.3,center:0.2,center_dual:0.0
"""
import argparse, sqlite3, sys
from collections import defaultdict
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))

STATE_DB = BASE / 'signals.db'  # v2温层
TUSHARE_DB = BASE / 'tushare.db'

# 榜单定义（顺序即默认权重顺序）
LISTS = [
    ('cmmr_plus',  'CMMR+',         0.40),
    ('fusion3m',   '三模型融合',     0.30),
    ('center',     '中枢版',         0.20),
    ('center_dual','中枢版+三模型',   0.10),
]

def norm(d): return str(d).replace('-', '')

def latest_signal_dates(c):
    """各信号源最新日（分开取，避免某榜滞后拖累全部）"""
    dates = {}
    dates['signal_history'] = c.execute(
        "SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0]
    dates['fusion_center'] = c.execute(
        "SELECT MAX(REPLACE(date,'-','')) FROM fusion_center_signals").fetchone()[0]
    return dates

def get_list(c, src, d):
    """返回 [(code, score)] top10，口径与 strategy_accounts_daily.get_signal_targets 一致"""
    picks = []
    if src == 'fusion3m':  # 三模型融合：final_score 百分位
        rows = c.execute(
            "SELECT stock_code, final_score FROM signal_history "
            "WHERE REPLACE(date,'-','')=? AND final_score IS NOT NULL "
            "ORDER BY final_score DESC LIMIT 10", (d,)).fetchall()
        picks = [(r[0].split('.')[0], float(r[1])) for r in rows]
    elif src == 'cmmr_plus':  # CMMR+：fusion_score_cmmr
        rows = c.execute(
            "SELECT stock_code, fusion_score_cmmr FROM signal_history "
            "WHERE REPLACE(date,'-','')=? AND fusion_score_cmmr IS NOT NULL AND fusion_score_cmmr > 0 "
            "ORDER BY fusion_score_cmmr DESC LIMIT 10", (d,)).fetchall()
        picks = [(r[0].split('.')[0], float(r[1])) for r in rows]
    elif src == 'center':  # 中枢版：强买按 score DESC
        rows = c.execute(
            "SELECT stock_code, score FROM fusion_center_signals "
            "WHERE REPLACE(date,'-','')=? AND signal='强买' "
            "ORDER BY score DESC LIMIT 10", (d,)).fetchall()
        picks = [(r[0], float(r[1])) for r in rows]
    elif src == 'center_dual':  # 中枢版+三模型：双信号百分位等权前15%取 top10
        ct = c.execute(
            "SELECT stock_code, score FROM fusion_center_signals "
            "WHERE REPLACE(date,'-','')=? AND score IS NOT NULL", (d,)).fetchall()
        md = c.execute(
            "SELECT stock_code, fusion_score FROM signal_history "
            "WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL", (d,)).fetchall()
        ctmap = {r[0]: float(r[1]) for r in ct}
        mdmap = {r[0].split('.')[0]: float(r[1]) for r in md}
        common = sorted(set(ctmap) & set(mdmap))
        if common:
            import numpy as np
            n = len(common)
            ct_rank = np.argsort(np.argsort([ctmap[x] for x in common])) + 1
            md_rank = np.argsort(np.argsort([mdmap[x] for x in common])) + 1
            comb = {x: 0.5 * ct_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                    for i, x in enumerate(common)}
            th = float(np.percentile(list(comb.values()), 85))
            picks = sorted([(x, s) for x, s in comb.items() if s >= th],
                           key=lambda x: x[1], reverse=True)[:10]
    return picks

def main():
    ap = argparse.ArgumentParser(description='四榜挑选 → 建议买入清单')
    ap.add_argument('--date', default=None, help='信号日 YYYYMMDD（默认各源最新）')
    ap.add_argument('--topn', type=int, default=10, help='每榜取前 N（默认 10）')
    ap.add_argument('--r2', type=float, default=7.0, help='R2 追高阈值 %（默认 7）')
    ap.add_argument('--weights', default=None,
                    help="榜间权重，如 'cmmr_plus:0.4,fusion3m:0.3,center:0.2,center_dual:0.1'")
    args = ap.parse_args()

    weights = {k: w for k, _, w in LISTS}
    if args.weights:
        for kv in args.weights.split(','):
            k, v = kv.split(':')
            if k in weights:
                weights[k] = float(v)

    c = sqlite3.connect(str(STATE_DB), timeout=30)
    import duckdb
    tdb = duckdb.connect(str(TUSHARE_DB), read_only=True)

    dates = latest_signal_dates(c)
    if args.date:
        d = norm(args.date)
    else:
        d = max(dates.values())  # 统一用最新信号日（各榜同一天）

    # 股票名/行业
    info = {}
    for r in tdb.execute("SELECT ts_code, name, industry FROM stock_basic").fetchall():
        info[r[0].split('.')[0]] = (r[1] or '', r[2] or '')
    # 今日/昨日收盘（R2 检查）
    td = tdb.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
    pd = tdb.execute(
        "SELECT MAX(trade_date) FROM daily WHERE trade_date < ?", (td,)).fetchone()[0]
    today_c, prev_c = {}, {}
    for r in tdb.execute(f"SELECT ts_code, close FROM daily WHERE trade_date='{td}'").fetchall():
        today_c[r[0].split('.')[0]] = r[1]
    for r in tdb.execute(f"SELECT ts_code, close FROM daily WHERE trade_date='{pd}'").fetchall():
        prev_c[r[0].split('.')[0]] = r[1]
    tdb.close()

    def pct_chg(code):
        if code in today_c and code in prev_c and prev_c[code]:
            return (today_c[code] / prev_c[code] - 1) * 100
        return None

    print(f'{"="*72}')
    print(f'四榜挑选 | 信号日 {d} | 行情日 {td}（昨日 {pd}）| R2 阈值 {args.r2}%')
    print(f'{"="*72}')

    # 拉四榜
    lists = {}
    for key, label, _ in LISTS:
        lst = get_list(c, key, d)
        lists[key] = lst[:args.topn]
        print(f'\n【{label}】({key})  {len(lst)} 只' + ('  ⚠️ 名单不足10只' if len(lst) < 10 else ''))
        for i, (code, score) in enumerate(lst[:args.topn]):
            name, ind = info.get(code, ('?', '?'))
            ch = pct_chg(code)
            ch_s = f'{ch:+.1f}%' if ch is not None else '--'
            flag = '  ⛔R2拦截' if (ch is not None and ch >= args.r2) else ''
            print(f'  {i+1:<3}{code:<8}{name:<8}{score:>8.1f}  {ch_s:<8}{ind}{flag}')

    # 重叠矩阵
    print(f'\n{"="*72}\n重叠矩阵（榜单间重合数）')
    keys = [k for k, _, _ in LISTS]
    labels = {k: l for k, l, _ in LISTS}
    sets = {k: set(x[0] for x in lists[k]) for k in keys}
    print(' ' * 12 + ''.join(f'{labels[k]:<12}' for k in keys))
    for k in keys:
        row = f'{labels[k]:<10}'
        for k2 in keys:
            row += f'{len(sets[k] & sets[k2]):<12}'
        print(row)

    # R2 过滤
    print(f'\n{"="*72}\nR2 追高过滤（今涨 ≥{args.r2}% 或涨停）')
    excluded = set()
    for k in keys:
        for code, score in lists[k]:
            ch = pct_chg(code)
            if ch is not None and ch >= args.r2:
                excluded.add(code)
    if excluded:
        for code in sorted(excluded):
            name, ind = info.get(code, ('?', '?'))
            print(f'  ⛔ {code} {name}: 今涨 {pct_chg(code):+.1f}%')
    else:
        print('  无拦截（全部可买）')

    # 建议买入（权重 → 榜内等权）
    print(f'\n{"="*72}\n建议买入清单（权重: ' +
          ' '.join(f'{labels[k]} {weights[k]*100:.0f}%' for k in keys) + '）')
    total_w = sum(weights[k] for k in keys)
    if total_w <= 0:
        print('  ❌ 权重合计为 0，无法分配')
        c.close()
        return
    recs = []
    for k in keys:
        if weights[k] <= 0:
            continue
        valid = [(code, score) for code, score in lists[k] if code not in excluded]
        if not valid:
            print(f'  ⚠️ {labels[k]}: 全部被 R2 拦截，该榜资金跳过')
            continue
        share = weights[k] / total_w / len(valid)
        for code, score in valid:
            recs.append((k, code, score, share))
    recs.sort(key=lambda x: (-x[3], -x[2]))
    print(f'\n  共 {len(recs)} 只建议买入，按权重排序：')
    for k, code, score, share in recs:
        name, ind = info.get(code, ('?', '?'))
        ch = pct_chg(code)
        ch_s = f'{ch:+.1f}%' if ch is not None else '--'
        print(f'  {code:<8}{name:<8}{labels[k]:<10} 分{score:>7.1f}  今涨{ch_s:<7} 建议仓位 {share*100:>5.1f}%  {ind}')

    # 行业分散
    print(f'\n{"="*72}\n行业分布（建议买入中）')
    ind_cnt = defaultdict(int)
    for _, code, _, _ in recs:
        ind_cnt[info.get(code, ('', ''))[1] or '未知'] += 1
    for ind, n in sorted(ind_cnt.items(), key=lambda x: -x[1]):
        warn = '  ⚠️ 超过3只' if n > 3 else ''
        print(f'  {ind}: {n} 只{warn}')

    c.close()
    print(f'\n{"="*72}\n说明: 榜内等权（回测无区分度）; R2 用昨日→今日涨幅（买入时点另看开盘实时涨幅）; '
          f'权重按历史强度可 --weights 覆盖')

if __name__ == '__main__':
    main()
