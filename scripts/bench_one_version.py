"""阶段2：加载已保存特征，评估单个版本"""
import numpy as np, lightgbm as lgb, sys, time, pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
MD = BASE / 'models'
FEAT = Path('/tmp/bench_features_clean.npz')

if not FEAT.exists():
    print(f"错误: 未找到特征文件 {FEAT}，请先跑 compute_bench_features.py")
    sys.exit(1)

def run_bench(ver):
    t0 = time.time()
    data = np.load(FEAT)
    X_all = data['X']; y_all = data['y']
    dates = data['dates']; codes = data['codes']
    
    print(f"{'='*60}")
    print(f"  版本: {ver}")
    print(f"  样本: {len(y_all):,}")
    print(f"{'='*60}")
    
    reg_m = lgb.Booster(model_file=str(MD / f'lgb_reg_{ver}.txt'))
    cls_m = lgb.Booster(model_file=str(MD / f'lgb_cls_{ver}.txt'))
    nf = reg_m.num_feature()
    
    # 特征索引
    idx = None
    if ver == 'v1': idx = list(range(20))
    elif ver == 'v2': idx = list(range(23))
    elif ver == 'v3': idx = list(range(20)) + list(range(23,31)) + list(range(20,23))  # 20base+8tech+3val
    elif ver == 'v4': idx = list(range(23)) + list(range(31, 70))  # 23base+39gtja
    elif ver == 'v5': idx = list(range(23)) + [31, 34, 35, 36]  # gtja_006,184,177,083
    
    if idx is None or len(idx) != nf:
        print(f"  × 特征不匹配: 需要{nf}维, 配置了{len(idx)}维")
        return
    
    X = np.nan_to_num(X_all[:, idx].astype(np.float64), nan=0.0)
    
    # z-score前23维
    for j in range(min(23, X.shape[1])):
        col = X[:,j]
        m,s = np.mean(col), np.std(col)
        if s > 0: X[:,j] = (col-m)/s
    
    pred_reg = reg_m.predict(X)
    pred_cls = cls_m.predict(X)
    
    reg_ic = spearmanr(pred_reg, y_all)[0]
    y_bin = (y_all > 0).astype(int)
    cls_auc = roc_auc_score(y_bin, pred_cls) if len(set(y_bin))>1 else 0
    
    df = pd.DataFrame({'date':dates,'code':codes,'pred':pred_reg,'ret':y_all})
    df = df.dropna(subset=['ret']).copy()
    
    spreads = []; top10p_rates = []
    top10_by_day = []
    for dt, g in df.groupby('date'):
        if len(g) < 20: continue
        g = g.sort_values('pred', ascending=False)
        n10 = max(len(g)//10, 5)
        top = g.iloc[:n10]; bot = g.iloc[-n10:]
        spreads.append(top['ret'].mean() - bot['ret'].mean())
        top10p_rates.append((top['ret'] > 0).mean())
        
        if len(g) >= 10:
            top10 = g.iloc[:10]
            top10_by_day.append((top10['ret'] > 0).mean())
    
    spread = np.mean(spreads) if spreads else 0
    top10p_win = np.mean(top10p_rates) if top10p_rates else 0
    top10_win = np.mean(top10_by_day) if top10_by_day else 0
    
    print(f"  维数:    {nf}")
    print(f"  回归IC:  {reg_ic:>+.4f}")
    print(f"  分类AUC: {cls_auc:>.4f}")
    print(f"  多空差:  {spread*100:>+.2f}%")
    print(f"  TOP10%:  {top10p_win*100:>.1f}%")
    print(f"  TOP10:   {top10_win*100:>.1f}%")
    print(f"  耗时:    {time.time()-t0:.1f}s")
    print()
    
    return {
        'ver': ver, 'nf': nf, 'reg_ic': reg_ic, 'cls_auc': cls_auc,
        'spread': spread, 'top10p': top10p_win, 'top10': top10_win
    }

if __name__ == '__main__':
    ver = sys.argv[1] if len(sys.argv) > 1 else None
    
    versions = sys.argv[1:] if len(sys.argv) > 1 else ['v1','v2','v3','v4','v5']
    
    for v in versions:
        if not (MD / f'lgb_reg_{v}.txt').exists():
            print(f"  跳过 {v}: 模型文件不存在")
            continue
        run_bench(v)
