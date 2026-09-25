#!/usr/bin/env python3
"""特征级 A/B 对比 v2: 推理管道 _compute_ml_features(feat_29)
原版(get_factor_from_db 读 stk_factor) vs 自算指标 → 29维特征逐维对比
本机调试用, 只读不写库。
"""
import duckdb, sys, random, time
import numpy as np
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

from core.scoring import _compute_ml_features, FACTOR_FIELDS
from scripts.compute_indicators import compute_all
import feat_tushare

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
TARGET_DATE = '20260825'
N_SAMPLE = 60

c = duckdb.connect(DB, read_only=True)
all_codes = [r[0] for r in c.execute("""
    SELECT DISTINCT ts_code FROM daily WHERE trade_date='20260825' ORDER BY ts_code
""").fetchall()]
random.seed(7)
codes = random.sample(all_codes, N_SAMPLE)
print(f"样本 {N_SAMPLE} 只 (8/25)")

# 1. 自算指标
t0 = time.time()
print("自算指标...")
self_inds = compute_all(codes, progress=30)
print(f"  耗时 {time.time()-t0:.0f}s")

# 2. 原版 feat_29
print("原版特征...")
r1_all = {}
for code in codes:
    sc = code.split('.')[0]
    try:
        f29, f38 = _compute_ml_features(sc, c, as_of_date=TARGET_DATE)
        if f29 is not None:
            r1_all[code] = f29
    except Exception as e:
        print(f"  {code} 原版异常: {str(e)[:80]}")

# 3. patch get_factor_from_db → 自算
print("自算版特征...")
orig = feat_tushare.get_factor_from_db
def fake_get_factor(code, dt, fields, conn):
    ts = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
    d = self_inds.get(ts, {}).get(dt, {})
    out = {}
    for f in fields:
        if f == 'kdj_k':
            v = d.get('kdj_k_bfq')
        elif f == 'cci':
            v = d.get('cci_bfq')
        elif f == 'rsi_12':
            v = d.get('rsi_bfq_12')
        else:
            v = d.get(f'{f}_bfq')
        if v is not None:
            out[f] = v
    return out
feat_tushare.get_factor_from_db = fake_get_factor
r2_all = {}
for code in codes:
    sc = code.split('.')[0]
    try:
        f29, f38 = _compute_ml_features(sc, c, as_of_date=TARGET_DATE)
        if f29 is not None:
            r2_all[code] = f29
    except Exception as e:
        print(f"  {code} 自算版异常: {str(e)[:80]}")
feat_tushare.get_factor_from_db = orig
c.close()

# 4. 对比
common = [k for k in r1_all if k in r2_all]
print(f"\n有效对比 {len(common)} 只 × 29 维")
diffs = []
for code in common:
    v1, v2 = r1_all[code], r2_all[code]
    for i in range(29):
        diffs.append((abs(float(v1[i]) - float(v2[i])), code, i))
diffs.sort(reverse=True)
a = np.array([x[0] for x in diffs])
print(f"完全一致(差=0): {np.mean(a==0):.4f}")
print(f"差<=1e-6: {np.mean(a<=1e-6):.4f}")
print(f"差<=1e-4: {np.mean(a<=1e-4):.4f}")
print(f"最大差: {a.max():.6g}")
print(f"\n差异最大的 8 个(维, 股票, 差):")
for d, code, i in diffs[:8]:
    print(f"  dim{i} {code} 差={d:.6g}")
# 因子三列(26/27/28)单独看
print(f"\n因子列(26=kdj_k, 27=cci, 28=rsi_12)差异:")
for i in (26, 27, 28):
    ds = [x[0] for x in diffs if x[2] == i]
    if ds:
        print(f"  dim{i}: max差={max(ds):.6g} 一致率={np.mean(np.array(ds)==0):.3f}")
