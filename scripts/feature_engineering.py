#!/usr/bin/env python3
"""特征工程 — 从全量数据计算新候选特征并测试IC"""
import json, sys, time, math
import numpy as np
from pathlib import Path
from scipy.stats import spearmanr, skew, kurtosis
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
DB_PATH = BASE / 'stock.db'
FWD_DAYS = 20
SAMPLE_LIMIT = 200000  # 抽样上限


def compute_candidate_features(closes, volumes, pcts, n=120):
    """计算一批候选特征，返回 dict {name: value}"""
    c = np.array(closes[-n:], dtype=np.float64)
    v = np.array(volumes[-n:], dtype=np.float64) if len(volumes) >= n else np.ones(n)
    p = np.array(pcts[-n:], dtype=np.float64) if len(pcts) >= n else np.zeros(n)
    lc = c[-1]

    feats = {}

    # ── 价格统计 ──
    feats['skew20'] = float(skew(c[-20:])) if len(c) >= 20 else 0
    feats['skew60'] = float(skew(c[-60:])) if len(c) >= 60 else 0
    feats['kurt20'] = float(kurtosis(c[-20:], fisher=False)) if len(c) >= 20 else 3
    feats['kurt60'] = float(kurtosis(c[-60:], fisher=False)) if len(c) >= 60 else 3

    # ── 连续涨跌 ──
    signs = np.sign(p[-20:])
    # 连续上涨天数
    up_streak = 0
    for s in reversed(signs):
        if s > 0: up_streak += 1
        else: break
    feats['up_streak'] = up_streak
    # 连续下跌天数
    dn_streak = 0
    for s in reversed(signs):
        if s < 0: dn_streak += 1
        else: break
    feats['dn_streak'] = dn_streak

    # 5日动量方向一致性（正的天数占比）
    feats['up_ratio5'] = np.sum(np.sign(p[-5:]) > 0) / 5.0 if len(p) >= 5 else 0.5
    feats['up_ratio10'] = np.sum(np.sign(p[-10:]) > 0) / 10.0 if len(p) >= 10 else 0.5

    # ── 价格位置 ──
    rl20, rh20 = np.min(c[-20:]), np.max(c[-20:])
    feats['pos20'] = (lc - rl20) / (rh20 - rl20) * 100 if rh20 != rl20 else 50.0
    rl60, rh60 = np.min(c[-60:]), np.max(c[-60:])
    feats['pos60'] = (lc - rl60) / (rh60 - rl60) * 100 if rh60 != rl60 else 50.0

    # ── 量价关系 ──
    if len(v) >= 20:
        # 量比
        vr = v[-1] / np.mean(v[-20:]) if np.mean(v[-20:]) > 0 else 1.0
        feats['vr'] = float(vr)
        # 放量上涨（量比>1.5 且涨）
        chg5 = lc / c[-5] - 1 if len(c) >= 5 else 0
        feats['vp_up'] = 1.0 if chg5 > 0.01 and vr > 1.5 else 0.0
        feats['vp_dn'] = 1.0 if chg5 < -0.01 and vr > 1.5 else 0.0
        # 缩量下跌（量比<0.7 且跌）
        feats['vp_shrink'] = 1.0 if chg5 < -0.01 and vr < 0.7 else 0.0
        # 量价背离（价涨量缩 或 价跌量增）
        feats['vp_div'] = 1.0 if (chg5 > 0 and vr < 0.8) or (chg5 < 0 and vr > 1.2) else 0.0

    # ── 波动率特征 ──
    feats['vol20'] = float(np.std(p[-20:]) * math.sqrt(252)) if len(p) >= 20 else 0
    feats['vol60'] = float(np.std(p[-60:]) * math.sqrt(252)) if len(p) >= 60 else 0
    # 波动率变化
    if len(p) >= 60:
        vol_old = np.std(p[-60:-20]) * math.sqrt(252)
        vol_new = np.std(p[-20:]) * math.sqrt(252)
        feats['vol_chg'] = float(vol_new / vol_old - 1) if vol_old > 0 else 0
    else:
        feats['vol_chg'] = 0.0

    # ── 均线乖离率 ──
    ma5 = np.mean(c[-5:]) if len(c) >= 5 else lc
    ma10 = np.mean(c[-10:]) if len(c) >= 10 else lc
    ma20 = np.mean(c[-20:]) if len(c) >= 20 else lc
    ma60 = np.mean(c[-60:]) if len(c) >= 60 else lc
    ma120 = np.mean(c)
    feats['bias5'] = float(lc / ma5 - 1)
    feats['bias10'] = float(lc / ma10 - 1)
    feats['bias20'] = float(lc / ma20 - 1)
    feats['bias60'] = float(lc / ma60 - 1)
    feats['bias120'] = float(lc / ma120 - 1)

    # 短期均线斜率（5日线性回归斜率）
    if len(c) >= 10:
        x = np.arange(5)
        y = c[-5:]
        slope = (np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean())**2)) if np.sum((x - x.mean())**2) > 0 else 0
        feats['slope5'] = float(slope)
    else:
        feats['slope5'] = 0.0
    if len(c) >= 20:
        x = np.arange(10)
        y = c[-10:]
        slope = (np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean())**2)) if np.sum((x - x.mean())**2) > 0 else 0
        feats['slope10'] = float(slope)
    else:
        feats['slope10'] = 0.0

    # ── 加速/减速 ──
    feats['accel'] = feats['slope5'] - feats['slope10'] if 'slope5' in feats and 'slope10' in feats else 0

    # ── 相对强弱（自身vs均线） ──
    feats['rel_str'] = float(chg5 - (ma20 / ma60 - 1)) if 'chg5' in locals() and ma60 > 0 else 0

    return feats


def main():
    t0 = time.time()
    print("="*65)
    print("📊 特征工程 — 候选特征IC测试")
    print(f"  标签: 未来{FWD_DAYS}日收益率")
    print(f"  抽样: {SAMPLE_LIMIT:,} 样本")
    print("="*65)

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # 获取股票列表
    stocks = [r[0] for r in conn.execute("""
        SELECT stock_code FROM stock_info
        WHERE stock_code NOT LIKE '8%' AND stock_code NOT LIKE '4%'
          AND board != '北交所' AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL)
        ORDER BY stock_code
    """).fetchall()]
    print(f"\n📡 股票池: {len(stocks)} 只")

    # 抽样日期（每个季度取一个）
    all_dates = sorted(set(str(r[0])[:10] for r in conn.execute("""
        SELECT DISTINCT date FROM stock_daily WHERE date >= '2015-01-01' AND date <= '2025-06-01'
        ORDER BY date
    """).fetchall()))
    # 取每月第一个交易日
    sample_dates = []
    seen_m = set()
    for d in all_dates:
        m = d[:7]
        if m not in seen_m:
            sample_dates.append(d)
            seen_m.add(m)
    sample_dates = sample_dates[:24]  # 最多24个月
    print(f"  抽样日期: {len(sample_dates)} 个")

    # 遍历收集样本
    all_feats = defaultdict(list)
    all_labels = []
    sampled = 0

    for di, ref_date in enumerate(sample_dates):
        for si, code in enumerate(stocks):
            rows = conn.execute(f"""
                SELECT date, close, volume, change_pct
                FROM stock_daily
                WHERE stock_code='{code}' AND date <= '{ref_date}'
                ORDER BY date DESC LIMIT 200
            """).fetchall()
            if len(rows) < 120:
                continue

            # 时间升序
            rows_rev = rows[::-1]
            closes = [float(r[1]) for r in rows_rev]
            volumes = [float(r[2] or 0) for r in rows_rev]
            pcts = [float(r[3] or 0) / 100.0 for r in rows_rev]

            # 候选特征
            feats = compute_candidate_features(closes, volumes, pcts)

            # 标签：查未来20日
            cur_close = closes[-1]
            fwd_rows = conn.execute(f"""
                SELECT close FROM stock_daily
                WHERE stock_code='{code}' AND date > '{ref_date}'
                ORDER BY date LIMIT {FWD_DAYS}
            """).fetchall()
            if len(fwd_rows) < FWD_DAYS:
                continue
            fwd_close = float(fwd_rows[-1][0])
            label = (fwd_close / cur_close - 1) * 100.0
            if abs(label) > 50:
                continue

            for name, val in feats.items():
                all_feats[name].append(val)
            all_labels.append(label)
            sampled += 1

            if sampled >= SAMPLE_LIMIT:
                break
        if sampled >= SAMPLE_LIMIT:
            break
        print(f"  [{di+1}/{len(sample_dates)}] {ref_date}  {sampled}样本  {time.time()-t0:.0f}s", flush=True)

    conn.close()

    if not all_labels:
        print("❌ 无样本")
        return

    labels = np.array(all_labels)
    print(f"\n总样本: {len(labels):,}")
    print(f"标签分布: 均值{np.mean(labels):+.2f}%  std{np.std(labels):.2f}%")

    # 计算每个特征的IC
    results = []
    for name, vals in all_feats.items():
        arr = np.array(vals, dtype=np.float64)
        if np.std(arr) < 1e-10:
            continue
        ic = float(spearmanr(arr, labels)[0])
        if np.isnan(ic):
            continue
        # 十分位spread
        order = np.argsort(arr)
        n = len(order)
        d1 = float(np.mean(labels[order[:n//10]]))
        d10 = float(np.mean(labels[order[-n//10:]]))
        spread = d10 - d1
        results.append({'name': name, 'ic': round(ic, 4), 'spread': round(spread, 2),
                        'd1': round(d1, 2), 'd10': round(d10, 2)})

    # 排序输出
    results.sort(key=lambda x: abs(x['ic']), reverse=True)

    print(f"\n{'特征名':<16} {'IC':>8} {'Spread':>8} {'D10':>8} {'D1':>8}")
    print(f"{'─'*48}")
    for r in results:
        bar = '█' * int(abs(r['ic']) * 200)
        print(f"{r['name']:<16} {r['ic']:>+8.4f} {r['spread']:>+7.2f}% {r['d10']:>+7.2f}% {r['d1']:>+7.2f}%  {bar}")

    # 跟现有36个特征的IC对比
    print(f"\n📊 对比: 现有模型特征 IC≈0.13 (训练集)")
    strong = [r for r in results if abs(r['ic']) >= 0.02]
    print(f"新候选特征中 IC>=0.02 的有 {len(strong)} 个:")
    for r in strong[:10]:
        print(f"  {r['name']:<16} IC={r['ic']:+5.4f}  Spread={r['spread']:+.2f}%")

    # 保存
    out = BASE / 'models' / 'feature_ic_results.json'
    with open(out, 'w') as f:
        json.dump({'features': results, 'samples': len(labels), 'time_sec': round(time.time()-t0)},
                  f, indent=2, ensure_ascii=False)
    print(f"\n💾 保存: {out}")
    print(f"⏱ {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
