#!/usr/bin/env python3
"""v4_big 影子对跑验证（2026-09-05）：samples_v4_big 验证段上 v4_big vs 生产 v3
同批样本公平对比：各自 norm_stats 标准化 → 逐日截面 RankIC / 预测 Spearman /
十分组 / Top10 等权未来收益 / 重叠度。结论：v4_big 是否 >= v3。"""
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy import stats
from pathlib import Path

BASE = Path.home() / ".hermes/stockdb"
V4D = BASE / "analysis/retrain_10d_v4"

def load_stats(path):
    d = json.load(open(path))
    return {int(k.replace("feat_", "")): v for k, v in d.items() if k.startswith("feat_")}

def std_scale(X, stats_dict):
    X = X.astype(float).copy()
    for j in range(X.shape[1]):
        st = stats_dict.get(j)
        if st is None:
            continue
        lo, hi, mu, sd = st["low"], st["high"], st["mean"], st["std"]
        col = np.clip(X[:, j], lo, hi)
        X[:, j] = (col - mu) / sd if sd and sd > 0 else col * 0.0
    return np.nan_to_num(X, nan=0.0)

print("加载样本...", flush=True)
df = pd.read_parquet(V4D / "samples_v4_big.parquet", columns=["date", "f0", "y"] +
                     [f"f{j}" for j in range(1, 31)])
# 验证段 = split_date 之后（与训练一致：split_date 2025-03-05）
split = "2025-03-05"
va = df[df["date"] >= split].reset_index(drop=True)
print(f"验证段样本: {len(va):,}  日期: {va.date.min()} ~ {va.date.max()}  天数: {va.date.nunique()}", flush=True)
feat_cols = [f"f{j}" for j in range(31)]
X = va[feat_cols].to_numpy(dtype=float)
y = va["y"].to_numpy(dtype=float)
dates = va["date"].to_numpy()

m3 = lgb.Booster(model_file=str(BASE / "models/lgb_reg_10d_v3.txt"))
m4 = lgb.Booster(model_file=str(V4D / "lgb_reg_10d_v4_big.txt"))
print(f"v3: {m3.num_trees()}树 / v4_big: {m4.num_trees()}树  特征 {m3.num_feature()}/{m4.num_feature()}", flush=True)

s3 = load_stats(BASE / "models/v10_v3_stats.json")
s4 = load_stats(V4D / "v10_v4_stats_big.json")
print(f"stats: v3 {len(s3)} 特征 / v4_big {len(s4)} 特征", flush=True)
X3 = std_scale(X, s3)
X4 = std_scale(X, s4)

p3 = m3.predict(X3)
p4 = m4.predict(X4)

def daily_stats(pred):
    recs = []
    for d in np.unique(dates):
        m = dates == d
        if m.sum() < 200:
            continue
        ic = stats.spearmanr(pred[m], y[m])[0]
        # Top10 等权未来收益（可交易视野）
        top = np.argsort(pred[m])[-10:]
        bot = np.argsort(pred[m])[:10]
        recs.append({"d": str(d), "n": int(m.sum()), "ic": ic,
                     "top10": float(np.mean(y[m][top])), "bot10": float(np.mean(y[m][bot]))})
    return pd.DataFrame(recs)

r3 = daily_stats(p3)
r4 = daily_stats(p4)
merged = r3.merge(r4, on="d", suffixes=("_v3", "_v4"))

print("\n=== 影子对跑结果（验证段逐日，同批样本）===")
print(f"{'指标':<32}{'v3(生产)':>12}{'v4_big':>12}")
print(f"{'验证天数':<32}{len(r3):>12}{len(r4):>12}")
print(f"{'日均截面RankIC':<32}{r3.ic.mean():>+12.4f}{r4.ic.mean():>+12.4f}")
print(f"{'IC正占比':<32}{(r3.ic > 0).mean()*100:>11.0f}%{(r4.ic > 0).mean()*100:>11.0f}%")
print(f"{'IC中位数':<32}{r3.ic.median():>+12.4f}{r4.ic.median():>+12.4f}")
print(f"{'Top10等权日均收益':<30}{r3.top10.mean()*100:>+11.3f}%{r4.top10.mean()*100:>+11.3f}%")
print(f"{'Top10正收益天数占比':<29}{(r3.top10>0).mean()*100:>11.0f}%{(r4.top10>0).mean()*100:>11.0f}%")

corr_pp = stats.spearmanr(p3, p4)[0]
corr_ic = merged.ic_v3.corr(merged.ic_v4)
print(f"\n两模型预测 Spearman: {corr_pp:+.4f}")
print(f"两模型逐日IC相关: {corr_ic:+.4f}")

# 十分组（全验证段）
def deciles(pred, label):
    order = np.argsort(pred)
    n = len(pred)
    d10 = n // 10
    out = []
    for k in range(10):
        seg = order[k*d10: (k+1)*d10] if k < 9 else order[9*d10:]
        out.append(np.mean(y[seg]) * 100)
    return out
d3, d4 = deciles(p3, "v3"), deciles(p4, "v4")
print("\n十分组未来10日收益(%):")
print("v3:", " ".join(f"{v:+.2f}" for v in d3))
print("v4:", " ".join(f"{v:+.2f}" for v in d4))

# 逐日 IC 胜负天数（同一天对比）
w3 = int((merged.ic_v3 > merged.ic_v4).sum())
w4 = int((merged.ic_v4 > merged.ic_v3).sum())
print(f"\n逐日IC胜负: v3赢 {w3} 天 / v4赢 {w4} 天（{len(merged)} 天可比）")

# 分布对比
print("\n=== 预测分布 ===")
for name, p in [("v3", p3), ("v4_big", p4)]:
    print(f"{name}: mean={p.mean():+.4f} std={p.std():.4f} min={p.min():.4f} max={p.max():.4f} 中位={np.median(p):+.4f}")

va.to_parquet(V4D / "_shadow_va_big.parquet", index=False)
np.savez(V4D / "_shadow_pred_big.npz", p3=p3, p4=p4, y=y, dates=dates)
print("\n影子对跑完成（中间结果已存 _shadow_va_big.parquet / _shadow_pred_big.npz）")
