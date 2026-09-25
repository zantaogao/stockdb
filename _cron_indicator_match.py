#!/usr/bin/env python3
"""正式对拍: 自算引擎 vs tushare stk_factor extra._bfq
200 只样本股 × 最近 60 交易日, 逐键输出 corr/MAE/一致率, 出正式报告。
"""
import duckdb, json, time, random, sys
import numpy as np
import pandas as pd

sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from scripts.compute_indicators import compute_all

DB = '/Users/zantao/.hermes/stockdb/tushare.db'
N_SAMPLE = 200
N_WINDOW = 60  # 对拍窗口天数

random.seed(42)
c = duckdb.connect(DB, read_only=True)

# 抽样本: 各板块混合 + 随机
all_codes = [r[0] for r in c.execute("SELECT DISTINCT ts_code FROM daily WHERE trade_date >= '20260701'").fetchall()]
print(f"候选 {len(all_codes)} 只, 抽 {N_SAMPLE}")
codes = random.sample(all_codes, N_SAMPLE)

t0 = time.time()
print("1/3 自算引擎计算样本股全历史指标...")
res = compute_all(codes, progress=50)

# 批量取 tushare 真值: 200股 × 近60天
print("2/3 读取 tushare extra 真值...")
dates = [r[0].replace('-', '') for r in c.execute(
    "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 60").fetchall()]
date_min = min(dates)
truth = {}  # (code, date8) -> {key: val}
rows = c.execute(f"""
    SELECT ts_code, trade_date, extra FROM stk_factor
    WHERE ts_code IN ({','.join(['?']*len(codes))}) AND trade_date >= '{date_min}'
""", codes).fetchall()
for ts, td, extra in rows:
    if not extra:
        continue
    try:
        d = json.loads(extra)
        truth[(ts, td.replace('-', ''))] = {k: v for k, v in d.items()
                                            if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v))}
    except Exception:
        pass
c.close()
print(f"  tushare 真值行: {len(truth)}")

# 3/3 逐键对拍
print("3/3 对拍汇总...")
all_keys = set()
for _, dd in res.items():
    for kv in dd.values():
        all_keys.update(kv.keys())
# 只对拍 tushare 有的键
t_keys = set()
for kv in truth.values():
    t_keys.update(kv.keys())
keys = sorted(all_keys & t_keys)

report = []
for key in keys:
    pairs = []
    for code, dd in res.items():
        for date8, kv in dd.items():
            if key in kv and (code, date8) in truth and key in truth[(code, date8)]:
                pairs.append((kv[key], truth[(code, date8)][key]))
    if len(pairs) < 500:
        continue
    arr_c = np.array([p[0] for p in pairs])
    arr_t = np.array([p[1] for p in pairs])
    corr = float(np.corrcoef(arr_c, arr_t)[0, 1])
    mae = float(np.mean(np.abs(arr_c - arr_t)))
    scale = np.mean(np.abs(arr_t)) + 1e-9
    rel = float(np.mean(np.abs(arr_c - arr_t) / scale))
    # 容差 1e-3: 覆盖 tushare 4位小数存储精度差异(实测 max<=5e-4)
    exact = float(np.mean(np.abs(arr_c - arr_t) < 1e-3))
    maxdiff = float(np.abs(arr_c - arr_t).max())
    report.append((key, corr, mae, rel, exact, len(pairs), maxdiff))

report.sort(key=lambda x: x[1])
print(f"\n{'键':<20} {'corr':<9} {'MAE':<11} {'relErr':<9} {'一致率':<8} {'max差':<9} {'n'}")
print("-" * 82)
n_pass = 0
for key, corr, mae, rel, exact, n, maxdiff in report:
    ok = corr > 0.999 and exact > 0.99
    n_pass += ok
    print(f"{key:<20} {corr:<9.6f} {mae:<11.4g} {rel:<9.4g} {exact:<8.4f} {maxdiff:<9.4g} {n}{' ✅' if ok else ' ❌'}")
print("-" * 82)
print(f"通过 {n_pass}/{len(report)} 键 (corr>0.999 且 一致率>99%, 容差1e-3)")

# 保存报告
with open('/tmp/indicator_match_report.txt', 'w') as f:
    f.write(f"样本 {N_SAMPLE} 股 × 窗口 {N_WINDOW} 天 (对拍日期 {date_min}~{max(dates)})\n")
    f.write(f"{'键':<20} {'corr':<9} {'MAE':<11} {'relErr':<9} {'一致率':<8} {'max差':<9} {'n'}\n")
    for key, corr, mae, rel, exact, n, maxdiff in report:
        f.write(f"{key:<20} {corr:<9.6f} {mae:<11.4g} {rel:<9.4g} {exact:<8.4f} {maxdiff:<9.4g} {n}\n")
    f.write(f"\n通过 {n_pass}/{len(report)}")
print(f"\n报告已存 /tmp/indicator_match_report.txt, 耗时 {time.time()-t0:.0f}s")
