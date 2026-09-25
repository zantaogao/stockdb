#!/usr/bin/env python3
"""验证 SELF_IND=1 真实改造路径: 默认 vs 自算库, score_stock 输出对比
走 feat_tushare.get_factor_from_db 的环境变量分支(非 monkey-patch)。
"""
import duckdb, sys, random, os
import numpy as np
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
TARGET_DATE = '20260825'
N_SAMPLE = 150

c = duckdb.connect(DB, read_only=True)
all_codes = [r[0] for r in c.execute("""
    SELECT DISTINCT ts_code FROM daily WHERE trade_date='20260825' ORDER BY ts_code
""").fetchall()]
random.seed(13)
codes = random.sample(all_codes, N_SAMPLE)

def run_all():
    from core.scoring import score_stock
    out = {}
    for code in codes:
        sc = code.split('.')[0]
        try:
            r = score_stock(sc, conn=c, as_of_date=TARGET_DATE)
            if r:
                out[code] = r
        except Exception:
            pass
    return out

print("默认版(读 stk_factor)...")
os.environ.pop('SELF_IND', None)
r1 = run_all()
print("SELF_IND=1(读 indicators.db)...")
os.environ['SELF_IND'] = '1'
r2 = run_all()
c.close()

common = [k for k in r1 if k in r2]
print(f"\n有效对比 {len(common)} 只")
for key in ['reg10_pred', 'reg20_pred', 'reg40_pred', 'fusion', 'final_score']:
    ds = [abs(float(r1[k][key]) - float(r2[k][key])) for k in common]
    a = np.array(ds)
    print(f"  {key:<12} max差={a.max():.5f} 完全一致={np.mean(a==0):.3f}")

def top10(d):
    return sorted(d.items(), key=lambda x: x[1]['fusion'], reverse=True)[:10]
t1 = top10(r1); t2 = top10(r2)
s1 = {k for k, _ in t1}; s2 = {k for k, _ in t2}
print(f"Top10 重合: {len(s1 & s2)}/10")
from scipy.stats import spearmanr
f1 = [r1[k]['fusion'] for k in common]; f2 = [r2[k]['fusion'] for k in common]
print(f"fusion 秩相关: {spearmanr(f1, f2).statistic:.6f}")
