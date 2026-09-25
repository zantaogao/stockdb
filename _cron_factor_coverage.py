#!/usr/bin/env python3
"""stk_factor 因子逐日覆盖检查 2026-08-08
1. 最近 5 个交易日每天行数 vs daily（行级覆盖）
2. 每个 extra 因子的非空率（因子级覆盖，抽样当天全部行）"""
import duckdb, json
from collections import Counter

TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
c = duckdb.connect(TUSHARE, read_only=True)

# 1. 行级覆盖：最近 5 个交易日
print("=" * 70)
print("1) 行级覆盖（stk_factor vs daily 每日行数）")
tds = [r[0] for r in c.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date >= '20260724' ORDER BY trade_date").fetchall()]
for d in tds[-8:]:
    n_sf = c.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date=?", (d,)).fetchone()[0]
    n_dy = c.execute("SELECT COUNT(*) FROM daily WHERE trade_date=?", (d,)).fetchone()[0]
    cov = n_sf / n_dy * 100 if n_dy else 0
    print(f"  {d}: stk_factor {n_sf} 行 vs daily {n_dy} 行 = {cov:.1f}%")

# 2. 因子级覆盖：最近 5 个交易日每个因子非空率
print("=" * 70)
print("2) 因子级覆盖（最近 5 个交易日, extra JSON 每键非空率）")
recent5 = tds[-5:]
per_day = {}
for d in recent5:
    rows = c.execute("SELECT extra FROM stk_factor WHERE trade_date=? AND extra IS NOT NULL", (d,)).fetchall()
    total = len(rows)
    key_cnt = Counter()
    key_nonnull = Counter()
    for (extra,) in rows:
        try:
            ed = json.loads(extra)
        except Exception:
            continue
        for k, v in ed.items():
            key_cnt[k] += 1
            if v is not None and v != '' and v != 0:
                key_nonnull[k] += 1
    per_day[d] = (total, key_cnt, key_nonnull)

# 汇总所有键
all_keys = set()
for d, (total, cnt, nn) in per_day.items():
    all_keys.update(cnt.keys())
print(f"最近 5 日共 {len(all_keys)} 个 extra 键")

# 分类统计
suffix_groups = {}
for k in sorted(all_keys):
    if k.endswith('_bfq'): g = '_bfq'
    elif k.endswith('_hfq'): g = '_hfq'
    elif k.endswith('_qfq'): g = '_qfq'
    else: g = '裸名'
    suffix_groups.setdefault(g, []).append(k)
print(f"后缀分布: { {g: len(v) for g, v in suffix_groups.items()} }")

# 检查每个键在每天的非空率
print("\n3) 每天每因子非空率 < 95% 的（缺失因子）:")
missing = {}
for d in recent5:
    total, cnt, nn = per_day[d]
    for k in all_keys:
        if k not in cnt:
            missing.setdefault(k, []).append((d, 0))
        else:
            rate = nn.get(k, 0) / cnt[k]
            if rate < 0.95:
                missing.setdefault(k, []).append((d, round(rate, 3)))
for k, v in sorted(missing.items()):
    print(f"  {k}: {v}")

if not missing:
    print("  ✅ 最近 5 个交易日所有因子非空率 >= 95%")

# 4. 全历史是否有因子某天全缺失
print("\n4) 全历史: 每个因子出现过几天 / 全程天数")
rows_all = c.execute("SELECT DISTINCT trade_date FROM stk_factor ORDER BY trade_date").fetchall()
n_days_sf = len(rows_all)
n_days_dy = len(tds)
print(f"  stk_factor 有数据天数: {n_days_sf}, daily 交易日数: {n_days_dy}")
# 抽样验证: 7/24-8/7 因子非空率（一天全量）
print("  最近一天(8/7) 每因子非空率 < 95% 的:")
total, cnt, nn = per_day[recent5[-1]]
low = [(k, round(nn.get(k,0)/cnt[k], 3)) for k in cnt if nn.get(k,0)/cnt[k] < 0.95]
print(f"  {recent5[-1]}: 共 {len(cnt)} 键, 非空率<95% 的 {len(low)} 个: {low[:15]}")
c.close()
