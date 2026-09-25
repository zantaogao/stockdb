#!/usr/bin/env python3
"""信号级 A/B: score_stock 输出 (原版 vs 自算指标)
对比 reg10/reg20/reg40/fusion 变化 + 排序稳定性。本机调试, 只读。
"""
import duckdb, sys, random, time
import numpy as np
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

from core.scoring import score_stock
from scripts.compute_indicators import compute_all
import feat_tushare

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
TARGET_DATE = '20260825'
N_SAMPLE = 200

c = duckdb.connect(DB, read_only=True)
all_codes = [r[0] for r in c.execute("""
    SELECT DISTINCT ts_code FROM daily WHERE trade_date='20260825' ORDER BY ts_code
""").fetchall()]
random.seed(11)
codes = random.sample(all_codes, N_SAMPLE)
print(f"样本 {N_SAMPLE} 只 (8/25)")

t0 = time.time()
print("自算指标...")
self_inds = compute_all(codes, progress=100)
print(f"  耗时 {time.time()-t0:.0f}s")

def run_all():
    out = {}
    for code in codes:
        sc = code.split('.')[0]
        try:
            r = score_stock(sc, conn=c, as_of_date=TARGET_DATE)
            if r:
                out[code] = r
        except Exception as e:
            pass
    return out

print("原版评分...")
r1 = run_all()
print("自算版评分...")
orig = feat_tushare.get_factor_from_db
def fake_get_factor(code, dt, fields, conn):
    ts = f"{code}.SH" if code.startswith(('6', '68', '9')) else f"{code}.SZ"
    d = self_inds.get(ts, {}).get(dt, {})
    out = {}
    for f in fields:
        if f == 'kdj_k': v = d.get('kdj_k_bfq')
        elif f == 'cci': v = d.get('cci_bfq')
        elif f == 'rsi_12': v = d.get('rsi_bfq_12')
        else: v = d.get(f'{f}_bfq')
        if v is not None: out[f] = v
    return out
feat_tushare.get_factor_from_db = fake_get_factor
r2 = run_all()
feat_tushare.get_factor_from_db = orig
c.close()

common = [k for k in r1 if k in r2]
print(f"\n有效对比 {len(common)} 只")
for key in ['reg10_pred', 'reg20_pred', 'reg40_pred', 'fusion', 'final_score']:
    ds = []
    for k in common:
        ds.append(abs(float(r1[k][key]) - float(r2[k][key])))
    a = np.array(ds)
    print(f"  {key:<12} max差={a.max():.5f} 均值={a.mean():.5f} 完全一致={np.mean(a==0):.3f} 差<=0.01={np.mean(a<=0.01):.3f}")

# Top10 排序对比 (按 fusion)
def top10(d):
    return sorted(d.items(), key=lambda x: x[1]['fusion'], reverse=True)[:10]
t1 = top10(r1); t2 = top10(r2)
s1 = {k for k, _ in t1}; s2 = {k for k, _ in t2}
print(f"\nTop10 重合: {len(s1 & s2)}/10")
print("原版 Top10:", [k.split('.')[0] for k, _ in t1])
print("自算 Top10:", [k.split('.')[0] for k, _ in t2])
# 排序相关性(全样本 fusion 秩)
from scipy.stats import spearmanr
f1 = [r1[k]['fusion'] for k in common]; f2 = [r2[k]['fusion'] for k in common]
print(f"fusion 秩相关(Spearman): {spearmanr(f1, f2).statistic:.6f}")
