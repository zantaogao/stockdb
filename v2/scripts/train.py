#!/usr/bin/env python3
"""
v2 统一训练脚本 — PC上运行
===========================
单一LightGBM回归模型，预测20日超额收益率。

用法:
    python3 train.py                          # 默认参数
    python3 train.py --train-end 2024-12-31   # 自定义切分
    python3 train.py --max-depth 3            # 更保守的模型

输出:
    models/lgb_v2.txt          — 模型文件
    models/norm_stats_v2.json  — 标准化统计量
    models/train_result_v2.json — IC/回测结果
"""
import argparse
import json
import time
from pathlib import Path
from datetime import datetime

import numpy as np
import lightgbm as lgb
from sklearn.metrics import mean_absolute_error, r2_score

# 项目路径
BASE = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(BASE))

from core.features import (
    FEAT_NAMES, N_FEATURES, winorize, standardize, save_norm_stats
)
from core.data import connect, get_stock_list


def ic_score(preds, targets):
    """Information Coefficient: Spearman rank correlation"""
    return float(np.corrcoef(preds, targets)[0, 1])


def decile_analysis(preds, targets, n_deciles=10):
    """分位分析: 按预测值分组看实际收益"""
    pred_arr = np.array(preds)
    tgt_arr = np.array(targets)

    # 按预测值排序
    sorted_idx = np.argsort(pred_arr)
    sorted_preds = pred_arr[sorted_idx]
    sorted_targets = tgt_arr[sorted_idx]

    n = len(sorted_preds)
    decile_size = n // n_deciles

    result = {}
    for i in range(n_deciles):
        start = i * decile_size
        end = start + decile_size if i < n_deciles - 1 else n
        decile_targets = sorted_targets[start:end]
        result[f'd{i+1}'] = float(np.mean(decile_targets))

    result['spread'] = result['d10'] - result['d1']
    return result


def evaluate_model(model, X, y, name=''):
    """评估模型，返回IC、MAE、分位分析"""
    preds = model.predict(X)
    ic = ic_score(preds, y)
    mae = mean_absolute_error(y, preds)

    # 命中率: pred>0的样本中实际收益>0的比例
    positive_pred_mask = preds > 0
    if np.sum(positive_pred_mask) > 100:
        hit_rate = float(np.mean(y[positive_pred_mask] > 0)) * 100
    else:
        hit_rate = 0

    deciles = decile_analysis(preds, y)

    return {
        'ic': round(ic, 4),
        'mae': round(mae, 4),
        'hit_rate': round(hit_rate, 1),
        'samples': len(y),
        **deciles,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train-start', default='2019-01-01')
    parser.add_argument('--train-end',   default='2023-12-31')
    parser.add_argument('--val-start',   default='2024-01-01')
    parser.add_argument('--val-end',     default='2024-12-31')
    parser.add_argument('--test-start',  default='2025-01-01')
    parser.add_argument('--test-end',    default=None)
    parser.add_argument('--max-depth',   type=int, default=4)
    parser.add_argument('--num-leaves',  type=int, default=8)
    parser.add_argument('--learning-rate', type=float, default=0.03)
    parser.add_argument('--n-estimators', type=int, default=2000)
    parser.add_argument('--early-stopping', type=int, default=50)
    parser.add_argument('--forward-days', type=int, default=20)
    args = parser.parse_args()

    print("=" * 60)
    print("v2 训练开始")
    print(f"  Train: {args.train_start} ~ {args.train_end}")
    print(f"  Val:   {args.val_start} ~ {args.val_end}")
    print(f"  Test:  {args.test_start} ~ {args.test_end or 'latest'}")
    print("=" * 60)

    t0 = time.time()

    # ─── 1. 获取股票列表 ──────────────────────────────────────
    conn = connect()
    stocks = get_stock_list(conn)
    conn.close()
    print(f"\n有效股票数: {len(stocks)}")

    if len(stocks) == 0:
        print("ERROR: 没有有效股票，检查数据库连接")
        return

    # ─── 2. 加载数据 ──────────────────────────────────────────
    def load_split(start, end):
        """加载一个时间切片的数据"""
        from core.data import load_all_for_training
        X_list, y_list = [], []

        for code, feat, target, date in load_all_for_training(
            stocks, start_date=start, end_date=end
        ):
            # 过滤NaN/Inf
            if np.any(np.isnan(feat)) or np.any(np.isinf(feat)):
                continue
            X_list.append(feat)
            y_list.append(target)

        X = np.array(X_list, dtype=np.float64)
        y = np.array(y_list, dtype=np.float64)
        print(f"  {start} ~ {end}: {len(y)} samples")
        return X, y

    print("\n加载训练集...")
    X_train, y_train = load_split(args.train_start, args.train_end)

    if len(X_train) < 1000:
        print(f"ERROR: 训练样本太少 ({len(X_train)})")
        return

    # ─── 3. 去极值 + 标准化（只在训练集上计算统计量）─────────────
    print("\n预处理...")
    X_train = winorize(X_train, method='mad', k=5.0)
    X_train_std, feat_mean, feat_std = standardize(X_train)

    # 保存标准化统计量
    model_dir = BASE / 'models'
    model_dir.mkdir(exist_ok=True)
    save_norm_stats(feat_mean, feat_std, str(model_dir / 'norm_stats_v2.json'))
    print(f"  特征维度: {N_FEATURES}")
    print(f"  保存标准化统计量到 models/norm_stats_v2.json")

    # ─── 4. 加载验证集（用训练集的统计量处理）─────────────────────
    print("\n加载验证集...")
    X_val, y_val = load_split(args.val_start, args.val_end)
    if len(X_val) > 0:
        X_val = winorize(X_val, method='mad', k=5.0)
        X_val_std, _, _ = standardize(X_val, mean=feat_mean, std=feat_std)

    # ─── 5. 加载测试集（用训练集的统计量处理）─────────────────────
    print("\n加载测试集...")
    test_end = args.test_end or '2099-12-31'
    X_test, y_test = load_split(args.test_start, test_end)
    if len(X_test) > 0:
        X_test = winorize(X_test, method='mad', k=5.0)
        X_test_std, _, _ = standardize(X_test, mean=feat_mean, std=feat_std)

    # ─── 6. 训练 LightGBM ──────────────────────────────────────
    print("\n" + "=" * 40)
    print("训练模型...")
    print(f"  max_depth: {args.max_depth}")
    print(f"  num_leaves: {args.num_leaves}")
    print(f"  learning_rate: {args.learning_rate}")
    print(f"  n_estimators: {args.n_estimators}")

    train_data = lgb.Dataset(X_train_std, label=y_train)

    if len(X_val_std) > 0:
        val_data = lgb.Dataset(X_val_std, label=y_val, reference=train_data)
        watchlist = [train_data, val_data]
    else:
        val_data = None
        watchlist = [train_data]

    params = {
        'objective': 'regression',
        'metric': 'mae',
        'boosting_type': 'gbdt',
        'max_depth': args.max_depth,
        'num_leaves': args.num_leaves,
        'learning_rate': args.learning_rate,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 1,
        'min_child_samples': 100,
        'verbose': -1,
        'seed': 42,
    }

    model = lgb.train(
        params,
        train_data,
        num_boost_round=args.n_estimators,
        valid_sets=watchlist,
        callbacks=[
            lgb.early_stopping(args.early_stopping),
            lgb.log_evaluation(100),
        ],
    )

    best_iters = model.best_iteration if hasattr(model, 'best_iteration') else args.n_estimators
    print(f"\n最佳迭代: {best_iters}")

    # ─── 7. 评估 ────────────────────────────────────────────────
    print("\n" + "=" * 40)
    print("模型评估:")

    train_eval = evaluate_model(model, X_train_std, y_train, 'train')
    print(f"\n  Train ({len(y_train)} samples):")
    for k, v in train_eval.items():
        if k != 'samples':
            print(f"    {k}: {v}")

    val_result = {}
    if len(X_val_std) > 0:
        val_eval = evaluate_model(model, X_val_std, y_val, 'val')
        val_result = {'val_ic': val_eval['ic'], 'val_mae': val_eval['mae']}
        print(f"\n  Val ({len(y_val)} samples):")
        for k, v in val_eval.items():
            if k != 'samples':
                print(f"    {k}: {v}")

    test_result = {}
    if len(X_test_std) > 0:
        test_eval = evaluate_model(model, X_test_std, y_test, 'test')
        test_result = {'test_ic': test_eval['ic'], 'test_mae': test_eval['mae']}
        print(f"\n  Test ({len(y_test)} samples):")
        for k, v in test_eval.items():
            if k != 'samples':
                print(f"    {k}: {v}")

    # ─── 8. Feature Importance ──────────────────────────────────
    importance = model.feature_importance(importance_type='gain')
    feat_imp = sorted(zip(FEAT_NAMES, importance), key=lambda x: x[1], reverse=True)
    print("\nFeature Importance (Top 10):")
    for name, imp in feat_imp[:10]:
        bar = '#' * int(imp / importance.max() * 30)
        print(f"  {name:20s} {imp:>8.0f} {bar}")

    # ─── 9. 保存模型 ─────────────────────────────────────────────
    model_path = str(model_dir / 'lgb_v2.txt')
    model.save_model(model_path)
    print(f"\n模型保存到: {model_path}")

    elapsed = time.time() - t0

    # ─── 10. 保存结果 ────────────────────────────────────────────
    result = {
        'version': 'v2',
        'objective': '20d_excess_return_pct',
        'feats': N_FEATURES,
        'feat_names': FEAT_NAMES,
        'trees': best_iters,
        'params': params,
        'split_train': f"{args.train_start}~{args.train_end}",
        'split_val': f"{args.val_start}~{args.val_end}",
        'split_test': f"{args.test_start}~{test_end}",
        **train_eval,
        **val_result,
        **test_result,
        'feature_importance': {name: int(imp) for name, imp in feat_imp},
        'time_sec': round(elapsed, 1),
    }

    result_path = str(model_dir / 'train_result_v2.json')
    with open(result_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\n结果保存到: {result_path}")
    print(f"总耗时: {elapsed:.0f}s")
    print("\nDone.")


if __name__ == '__main__':
    main()
