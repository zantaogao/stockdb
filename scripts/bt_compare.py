#!/usr/bin/env python3
"""旧模型 v7 vs 新模型 在同一条特征管道下对比"""
import json, sys, time
import numpy as np
import lightgbm as lgb
from pathlib import Path
from scipy.stats import spearmanr

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.features import compute_raw_features, standardize_v5, _load_index_cache
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'
DB_PATH = BASE / 'stock.db'
TEST_START = '2025-01-01'
TEST_END = '2026-06-01'
SAMPLE_LIMIT = 50000  # 每只股票最多取样本数


def load_norm_stats(path):
    with open(path) as f:
        return json.load(f)


def predict(model, feat, norm_stats, n_feats):
    """标准化+预测"""
    for j in range(min(len(feat), n_feats)):
        key = f'feat_{j}'
        if key in norm_stats and norm_stats[key]['std'] > 0:
            s = norm_stats[key]
            feat[j] = max(feat[j], s['low'])
            feat[j] = min(feat[j], s['high'])
            feat[j] = (feat[j] - s['mean']) / s['std']
    return float(model.predict(feat[:n_feats].reshape(1, -1))[0])


def main():
    t0 = time.time()
    print("="*60)
    print("📊 旧模型 v7 vs 新模型 对比")
    print(f"  数据: {TEST_START} ~ {TEST_END}")
    print("="*60)

    # 加载模型
    new_model = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_reg_model.txt'))
    old_model = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_reg_v7.txt'))
    new_norm = load_norm_stats(MODEL_DIR / 'v6_norm_stats.json')
    # v7标准化用旧版
    old_norm_path = MODEL_DIR / 'v6_norm_stats_20d_tdx.json'
    old_norm = {}
    if old_norm_path.exists():
        old_norm = load_norm_stats(old_norm_path)

    print(f"  新模型: {new_model.num_trees()}棵树, {new_model.num_feature()}维")
    print(f"  旧v7:   {old_model.num_trees()}棵树, {old_model.num_feature()}维")

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    _load_index_cache(conn)

    # 获取测试期间有数据的股票
    stocks = [r[0] for r in conn.execute(f"""
        SELECT DISTINCT sd.stock_code FROM stock_daily sd
        JOIN stock_info si ON sd.stock_code = si.stock_code
        WHERE sd.date >= '{TEST_START}' AND sd.date <= '{TEST_END}'
          AND si.stock_code NOT LIKE '8%' AND si.stock_code NOT LIKE '4%'
          AND si.board != '北交所' AND (si.stock_name NOT LIKE '%ST%' OR si.stock_name IS NULL)
        ORDER BY sd.stock_code
    """).fetchall()]
    print(f"  股票: {len(stocks)} 只")

    # 抽样日期（取测试期内每月15号附近）
    dates_raw = [str(r[0])[:10] for r in conn.execute(f"""
        SELECT DISTINCT date FROM stock_daily
        WHERE date >= '{TEST_START}' AND date <= '{TEST_END}'
        ORDER BY date
    """).fetchall()]
    sample_dates = []
    seen_m = set()
    for d in dates_raw:
        m = d[:7]
        if m not in seen_m:
            sample_dates.append(d)
            seen_m.add(m)

    sample_dates = sample_dates[:12]  # 最多12个月
    print(f"  抽样日期: {len(sample_dates)} 个 ({sample_dates[0]} ~ {sample_dates[-1]})")

    new_preds, old_preds, actuals = [], [], []
    sampled = 0

    for di, ref_date in enumerate(sample_dates):
        for si, code in enumerate(stocks):
            rows = conn.execute(f"""
                SELECT date, close, open, high, low, change_pct, volume, amount
                FROM stock_daily
                WHERE stock_code='{code}' AND date <= '{ref_date}'
                ORDER BY date DESC LIMIT 200
            """).fetchall()
            if len(rows) < 130:
                continue

            # 前复权收盘价（用于标签）
            closes_raw = [float(r[1]) for r in rows[::-1]]

            # 特征
            base_raw, dt_str = compute_raw_features(code, rows, conn)
            if base_raw is None:
                continue
            feat = standardize_v5(base_raw.copy())

            # 补齐37维（新模型需要）
            while len(feat) < 37:
                feat = np.append(feat, 0.0)
            feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)[:37]

            # 两个模型预测
            new_p = predict(new_model, feat.copy(), new_norm, 37)
            old_p = predict(old_model, feat.copy(), old_norm, 27)

            # 标签
            fwd_close = closes_raw[-1]  # 最新=当日
            # 找到20日后收盘价
            if len(closes_raw) >= 120 + 20:
                cur_close = closes_raw[119]  # 窗口末尾
                fwd = closes_raw[119 + 20] if len(closes_raw) > 119 + 20 else closes_raw[-1]
                label = (fwd / cur_close - 1) * 100.0
                if abs(label) > 50:
                    continue
            else:
                continue

            new_preds.append(new_p)
            old_preds.append(old_p)
            actuals.append(label)
            sampled += 1

            if sampled >= SAMPLE_LIMIT:
                break
        if sampled >= SAMPLE_LIMIT:
            break

        print(f"  [{di+1}/{len(sample_dates)}] {ref_date}  {sampled}样本  {time.time()-t0:.0f}s", flush=True)

    conn.close()

    if not new_preds:
        print("无样本")
        return

    new_p = np.array(new_preds)
    old_p = np.array(old_preds)
    act = np.array(actuals)

    def evaluate(name, preds):
        ic = spearmanr(preds, act)[0]
        o = np.argsort(preds)
        n = len(o)
        d1 = np.mean(act[o[:n//10]])
        d10 = np.mean(act[o[-n//10:]])
        deciles = [np.mean(act[o[g*n//10:(g+1)*n//10]]) for g in range(10)]
        return {'ic': round(ic,4), 'd1': round(d1,2), 'd10': round(d10,2),
                'spread': round(d10-d1,2), 'hit': round(np.mean(act[o[-n//10:]]>0)*100,1),
                'deciles': [round(d,2) for d in deciles]}

    nr = evaluate('新模型', new_p)
    or_ = evaluate('旧v7', old_p)

    print(f"\n{'指标':<20} {'新模型(37维)':>14} {'旧v7(27维)':>14} {'差距':>10}")
    print(f"{'─'*58}")
    print(f"{'样本数':<20} {len(new_p):>14,d} {len(old_p):>14,d}")
    print(f"{'Rank IC':<20} {nr['ic']:>14.4f} {or_['ic']:>14.4f} {nr['ic']-or_['ic']:>+10.4f}")
    print(f"{'多空差':<20} {nr['spread']:>+13.2f}% {or_['spread']:>+13.2f}% {nr['spread']-or_['spread']:>+10.2f}%")
    print(f"{'D10命中':<20} {nr['hit']:>13.1f}% {or_['hit']:>13.1f}% {nr['hit']-or_['hit']:>+9.1f}%")

    print(f"\n测试集十分位:")
    print(f"{'分组':<8} {'新模型':>10} {'旧v7':>10}")
    print(f"{'─'*28}")
    for g in range(10):
        print(f"{'组'+str(g+1):<8} {nr['deciles'][g]:>+9.2f}% {or_['deciles'][g]:>+9.2f}%")

    # 保存
    res = {'samples': len(new_p), 'new': nr, 'old': or_, 'time_sec': round(time.time()-t0)}
    with open(MODEL_DIR / 'bt_model_compare.json', 'w') as f:
        json.dump(res, f, indent=2)
    print(f"\n💾 保存: {MODEL_DIR / 'bt_model_compare.json'}")
    print(f"⏱ {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
