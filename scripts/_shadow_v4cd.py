#!/usr/bin/env python3
"""v4c/v4d 影子评估（2026-09-06 修正口径）：v3 / v4_big / v4c / v4d 统一对比
段1 全样本外 359 天（2025-03-05 起，v4 系样本外；v3 该段 93% 样本内仅参考）
段2 真·双干净段（2026-07-18 起 25 天，双方纯样本外）= 决策依据
v4d 无 stats 文件 → 按 _train_v4d_0905 同口径从训练段现场重算（31维 clip+zscore）
特征: v3/v4_big=31(f0..f30) | v4c=+f31_touch20/f32_wick20/f33_pvcorr20 | v4d=+f39_vol_diverge/f32_zha20/f34_overnight_share/f43_turn_cv20/f44_skew20(原值NaN)
"""
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy import stats
from pathlib import Path

BASE = Path.home() / ".hermes/stockdb"
V4D = BASE / "analysis/retrain_10d_v4"

def load_stats_any(path):
    d = json.load(open(path))
    out = {}
    for k, v in d.items():
        if k.startswith("_"):
            continue
        idx = k.replace("feat_", "")
        if idx.isdigit():
            out[int(idx)] = v
        else:
            out[k] = v  # 特征名键（如 f31_touch20）
    return out

def scale_col(v, st):
    lo, hi, mu, sd = st["low"], st["high"], st["mean"], st["std"]
    c = np.clip(v, lo, hi)
    return (c - mu) / sd if sd and sd > 0 else c * 0.0

print("加载样本...", flush=True)
sm = pd.read_parquet(V4D / "samples_v4c.parquet")
uf = pd.read_parquet(V4D / "_uncon_feats.parquet").rename(columns={"symbol": "code"})
# 与 samples_v4c 重复的 3 列以 samples 为准（训练同口径），避免 merge 后缀冲突
uf = uf.drop(columns=[c for c in ["f31_touch20", "f32_wick20", "f33_pvcorr20"] if c in uf.columns])
df = sm.merge(uf, on=["code", "date"], how="left")
print(f"样本 {len(df):,}  日期 {df.date.min()} ~ {df.date.max()}", flush=True)
split = "2025-03-05"
va = df[df["date"] >= split].reset_index(drop=True)
y = va["y"].to_numpy(float)
dates = va["date"].to_numpy()
print(f"验证段 {len(va):,} 样本 {va.date.nunique()} 天", flush=True)

F31 = [f"f{j}" for j in range(31)]
V4C_EXTRA = ["f31_touch20", "f32_wick20", "f33_pvcorr20"]
V4D_EXTRA = ["f39_vol_diverge", "f32_zha20", "f34_overnight_share", "f43_turn_cv20", "f44_skew20"]

# 标准化映射
def prep(cols, std_map, raw_keep=()):
    X = va[list(cols)].to_numpy(float).copy()
    for j, c in enumerate(cols):
        st = std_map.get(c) or std_map.get(j)  # 特征名键 或 序号键
        if st:
            X[:, j] = scale_col(X[:, j], st)
        elif c in raw_keep:
            X[:, j] = np.where(np.isfinite(X[:, j]), X[:, j], np.nan)
    return X

models = {}

# v3
s3 = load_stats_any(BASE / "models/v10_v3_stats.json")
m3 = lgb.Booster(model_file=str(BASE / "models/lgb_reg_10d_v3.txt"))
models["v3"] = (m3, prep(F31, s3))

# v4_big
s4b = load_stats_any(V4D / "v10_v4_stats_big.json")
m4b = lgb.Booster(model_file=str(V4D / "lgb_reg_10d_v4_big.txt"))
models["v4_big"] = (m4b, prep(F31, s4b))

# v4c（31+3 全 clip+zscore）
s4c = load_stats_any(V4D / "v10_v4c_stats.json")
m4c = lgb.Booster(model_file=str(V4D / "lgb_reg_v4c.txt"))
models["v4c"] = (m4c, prep(F31 + V4C_EXTRA, s4c))

# v4d：stats 现场重算（训练段 date < split，31 维同口径）
tr = df[df["date"] < split]
Xtr = tr[F31].to_numpy(float).copy()
s4d = {}
for j in range(31):
    v = Xtr[:, j]; v = v[np.isfinite(v)]
    lo, hi = np.percentile(v, 1), np.percentile(v, 99)
    s4d[j] = {"mean": float(v.mean()), "std": float(v.std()), "low": float(lo), "high": float(hi)}
m4d = lgb.Booster(model_file=str(V4D / "lgb_reg_v4d.txt"))
models["v4d"] = (m4d, prep(F31 + V4D_EXTRA, s4d, raw_keep=set(V4D_EXTRA)))

# 逐日 IC + Top10
def run_seg(lo, tag):
    m = dates >= lo
    dd = np.unique(dates[m])
    print(f"\n{'='*74}\n{tag}（{len(dd)} 交易日，{lo} 起）\n{'='*74}")
    rows = {}
    for name, (mdl, X) in models.items():
        p = mdl.predict(X)
        ics, tops = [], []
        for d in dd:
            mm = (dates == d) & m
            if mm.sum() < 200:
                continue
            ics.append(stats.spearmanr(p[mm], y[mm])[0])
            tops.append(np.mean(y[mm][np.argsort(p[mm])[-10:]]))
        rows[name] = {"ic": np.array(ics), "top": np.array(tops), "pred": p}
    print(f"{'模型':<10}{'日均IC':>10}{'IC正占比':>9}{'IC中位':>9}{'Top10日均':>11}{'Top10正占比':>11}")
    for name, r in rows.items():
        print(f"{name:<10}{r['ic'].mean():>+10.4f}{(r['ic']>0).mean()*100:>8.0f}%{np.median(r['ic']):>+9.4f}{r['top'].mean()*100:>+10.2f}%{(r['top']>0).mean()*100:>10.0f}%")
    # vs v3 配对检验（全模型）
    print("\n配对检验（vs v3，同天配对）：")
    for name, r in rows.items():
        if name == "v3":
            continue
        n = min(len(r["ic"]), len(rows["v3"]["ic"]))
        tt = stats.ttest_rel(r["ic"][:n], rows["v3"]["ic"][:n])
        print(f"  {name:<10} vs v3: 差={np.mean(r['ic'][:n]-rows['v3']['ic'][:n]):+.4f}  t={tt.statistic:+.2f}  p={tt.pvalue:.4f}  逐日胜负 {int((r['ic'][:n]>rows['v3']['ic'][:n]).sum())}:{int((r['ic'][:n]<rows['v3']['ic'][:n]).sum())}")
    return rows

r_all = run_seg(split, "段1 全样本外 359 天（v3 该段 ~93% 样本内，仅参考）")
r_clean = run_seg("2026-07-18", "段2 真·双干净段 25 天（2026-07-18 起，决策依据）")

# 预测相关
print("\n干净段预测 Spearman（25天样本上）：")
for a in ["v3", "v4_big", "v4c", "v4d"]:
    for b in ["v4_big", "v4c", "v4d"]:
        if a >= b:
            continue
        m = dates >= "20260718"
        rho = stats.spearmanr(r_all[a]["pred"][m], r_all[b]["pred"][m])[0]
        print(f"  {a} vs {b}: {rho:+.3f}")
