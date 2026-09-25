"""模型质量检测：过拟合、特征数、树结构、推理测试"""
import re
import json
import numpy as np
import lightgbm as lgb
from pathlib import Path

MODEL_DIR = Path.home() / '.hermes' / 'stockdb' / 'models'

FILES = {
    '20d_reg':  'lgb_reg_model.txt',
    '40d_reg':  'lgb_reg_40d.txt',
    '10d_reg':  'lgb_reg_10d.txt',
    'cls27':    'lgb_cls_model.txt',
}

def check_model(name, path):
    if not path.exists():
        print(f"\n=== {name}: MISSING ===")
        return
    
    print(f"\n{'='*60}")
    print(f"=== {name} ===")
    print(f"路径: {path}")
    
    with open(path) as f:
        content = f.read()
    
    # 树数
    trees_raw = content.split('\n\nTree=')
    n_trees = len(trees_raw)
    print(f"树数: {n_trees}")
    
    # 特征数
    fi = re.search(r'max_feature_idx=(\d+)', content)
    n_features = int(fi.group(1)) + 1 if fi else None
    print(f"特征数: {n_features}")
    
    # shrinkage 检查
    shrinkages = re.findall(r'shrinkage=([^\n]+)', content)
    if shrinkages:
        s0 = float(shrinkages[0].strip()) if shrinkages else None
        s_mid = float(shrinkages[n_trees//2].strip()) if n_trees > 1 else None
        print(f"shrinkage: Tree0={s0}, Tree{n_trees//2}={s_mid}")
        # 检查是否一致
        s_set = set(float(x.strip()) for x in shrinkages[1:])
        if len(s_set) > 1:
            print(f"  WARNING: shrinkage 不一致! 唯一值: {s_set}")
    
    # 叶子值分析（对比早期 vs 晚期）
    trees = content.split('\n\nTree=')
    early_indices = [0, 1, 2, 3, 4]
    late_indices = list(range(max(0, n_trees-5), n_trees))
    
    all_early_std = []
    all_late_std = []
    
    print(f"\n叶子值范围:")
    for ti in early_indices + late_indices:
        tree_text = trees[ti]
        m = re.search(r'leaf_value=([^\n]+)', tree_text)
        if m:
            vals = [float(x) for x in m.group(1).split()]
            mn, mx, mean_v, std_v = min(vals), max(vals), np.mean(vals), np.std(vals)
            tag = f"Tree {ti}"
            print(f"  {tag}: [{mn:+.4f}, {mx:+.4f}] mean={mean_v:+.4f} std={std_v:.4f}")
            if ti in early_indices:
                all_early_std.append(std_v)
            else:
                all_late_std.append(std_v)
    
    if all_early_std and all_late_std:
        avg_early = np.mean(all_early_std)
        avg_late = np.mean(all_late_std)
        ratio = avg_late / avg_early if avg_early > 0 else 0
        print(f"\n叶子std对比: 早期avg={avg_early:.4f}, 晚期avg={avg_late:.4f}, 比率={ratio:.2f}")
        if ratio > 1.5:
            print("  WARNING: 晚期叶子std膨胀 > 1.5x，可能过拟合噪声!")
        elif ratio < 0.8:
            print("  OK: 晚期叶子std收缩，正常学习")
        else:
            print("  OK: 叶子std基本稳定")
    
    # 最后一棵树叶子均值
    last_tree = trees[-1]
    m = re.search(r'leaf_value=([^\n]+)', last_tree)
    if m:
        vals = [float(x) for x in m.group(1).split()]
        mean_last = np.mean(vals)
        if abs(mean_last) > 0.01:
            print(f"  WARNING: 最后一棵树叶均值偏离零 ({mean_last:+.4f})")
        else:
            print(f"  OK: 最后一棵树叶均值接近零 ({mean_last:+.4f})")
    
    # 加载模型做推理测试
    model = lgb.Booster(model_file=str(path))
    
    # 特征重要性 (gain)
    imp = model.feature_importance(importance_type='gain')
    total_imp = sum(imp)
    if total_imp > 0:
        pairs = sorted(enumerate(imp), key=lambda x: -x[1])
        print(f"\n特征重要性 (Top 5):")
        top5_pct = 0
        for idx, gain in pairs[:5]:
            pct = gain / total_imp * 100
            print(f"  feat_{idx}: {pct:.1f}%")
            top5_pct += pct
        if top5_pct > 60:
            print(f"  WARNING: Top5特征占 {top5_pct:.1f}%，信号过于集中")
        
        # 检查死特征
        dead = [idx for idx, g in enumerate(imp) if g == 0]
        if dead:
            print(f"  死特征({len(dead)}个): {dead[:10]}{'...' if len(dead)>10 else ''}")
    
    # 推理测试
    if n_features:
        test_input = np.zeros((1, n_features), dtype=np.float64)
        try:
            pred = model.predict(test_input)[0]
            print(f"\n推理测试: input=全零 → pred={pred:.4f}")
        except Exception as e:
            print(f"\n推理测试: FAIL - {e}")
    
    # 期望特征数检查
    expected = {
        '20d_reg': 30,  # 26 base + 4 GTJA
        '40d_reg': 27,  # 23 base + 4 GTJA
        '10d_reg': 30,  # 26 base + 4 GTJA
        'cls27': 27,    # 20 base + 3 + 4 GTJA
    }
    exp = expected.get(name)
    if exp and n_features:
        if n_features == exp:
            print(f"  特征数匹配: {n_features} (期望 {exp}) ✓")
        else:
            print(f"  WARNING: 特征数不匹配! 实际 {n_features}, 期望 {exp}")


def check_stats(name, path):
    if not path.exists():
        return
    print(f"\n--- {name} 统计量 ---")
    with open(path) as f:
        stats = json.load(f)
    dead = []
    for k, v in sorted(stats.items()):
        if v['std'] < 0.001:
            dead.append(k)
        elif v['high'] - v['low'] < 0.01:
            dead.append(k)
    if dead:
        print(f"  疑似死特征: {dead}")
    else:
        print(f"  所有特征活跃 ✓")


def check_gtja():
    gtja_path = Path.home() / '.hermes' / 'stockdb' / 'gtja_signals.pkl.gz'
    import gzip, pickle
    if not gtja_path.exists():
        print(f"\nGTJA: MISSING")
        return
    try:
        with gzip.open(str(gtja_path), 'rb') as f:
            data = pickle.load(f)
        print(f"\nGTJA因子:")
        for gn, df in data.items():
            print(f"  {gn}: shape={df.shape}, 最新日期={df.index[-1][:10]}")
            # 检查最近数据
            recent = df.iloc[-10:]
            nonzero = (recent != 0).sum().sum()
            total = recent.size
            print(f"    最近10天非零率: {nonzero}/{total} ({nonzero/total*100:.0f}%)")
            if nonzero / total < 0.3:
                print(f"    WARNING: 最近数据稀疏，信号可能弱")
    except Exception as e:
        print(f"\nGTJA: LOAD ERROR - {e}")


if __name__ == '__main__':
    for name, fname in FILES.items():
        check_model(name, MODEL_DIR / fname)
    
    check_stats('20d_stats', MODEL_DIR / 'v6_norm_stats.json')
    check_stats('40d_stats', MODEL_DIR / 'v6_norm_stats_40d.json')
    check_stats('10d_stats', MODEL_DIR / 'v10_norm_stats.json')
    
    check_gtja()
    
    print(f"\n{'='*60}")
    print("总结:")
    print("  过拟合 = 晚期叶子std膨胀 + 叶子均值偏离零")
    print("  特征数不匹配 = 推理结果不可信")
    print("  死特征多 = 训练浪费，但推理不受影响")
    print("  GTJA稀疏 = 40d模型退化风险（GTJA占24%增益）")
