#!/usr/bin/env python3
"""双轨对比: 默认(stk_factor) vs 自算(indicators.db) 全市场评分 Top10 重合率
只读, 不写 signals.db。输出到 /tmp/selfind_compare.log, 22:05 cron 跑。
"""
import duckdb, sys, os, time
import numpy as np
from pathlib import Path

sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
LOG = '/tmp/selfind_compare.log'

# 目标日: daily 最新, 且 stk_factor 有数据(滞后1天常态→用最近有因子的日)
c = duckdb.connect(DB, read_only=True)
mx_sf = str(c.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]).replace('-', '')
print(f"stk_factor 最新: {mx_sf}", flush=True)
TARGET_DATE = mx_sf

codes = [r[0] for r in c.execute(
    "SELECT DISTINCT ts_code FROM daily WHERE trade_date=?", [TARGET_DATE]).fetchall()]
# 排除北交所(8/4/92开头)
codes = [x for x in codes if not x.startswith(('8', '4', '92'))]
print(f"全市场 {len(codes)} 只 (排除北交所)", flush=True)

def run_all(use_self):
    from core.scoring import score_stock
    if use_self:
        os.environ['SELF_IND'] = '1'
    else:
        os.environ.pop('SELF_IND', None)
    out = {}
    t0 = time.time()
    for i, code in enumerate(codes):
        sc = code.split('.')[0]
        try:
            r = score_stock(sc, conn=c, as_of_date=TARGET_DATE)
            if r:
                out[code] = r
        except Exception:
            pass
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(codes)} ({time.time()-t0:.0f}s)", flush=True)
    return out

print("默认版全市场评分...", flush=True)
r1 = run_all(False)
print("自算版全市场评分...", flush=True)
r2 = run_all(True)
c.close()

common = [k for k in r1 if k in r2]
def top10(d):
    return sorted(d.items(), key=lambda x: x[1]['fusion'], reverse=True)[:10]
t1 = {k for k, _ in top10(r1)}
t2 = {k for k, _ in top10(r2)}
overlap = len(t1 & t2)
from scipy.stats import spearmanr
f1 = [r1[k]['fusion'] for k in common]; f2 = [r2[k]['fusion'] for k in common]
rho = spearmanr(f1, f2).statistic if len(common) > 10 else 0.0

lines = [
    f"===== 双轨对比 {TARGET_DATE} =====",
    f"有效股票: {len(common)}",
    f"Top10 重合: {overlap}/10",
    f"Top10 差异(默认有自算无): {sorted(t1-t2)}",
    f"Top10 差异(自算有默认无): {sorted(t2-t1)}",
    f"fusion 秩相关: {rho:.6f}",
    f"默认Top10: {[k.split('.')[0] for k,_ in top10(r1)]}",
    f"自算Top10: {[k.split('.')[0] for k,_ in top10(r2)]}",
    "=" * 30,
]
out = "\n".join(lines)
print(out, flush=True)
with open(LOG, 'a') as f:
    f.write(out + "\n")
