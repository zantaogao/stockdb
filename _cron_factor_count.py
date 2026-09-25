#!/usr/bin/env python3
"""统计数据库中的因子数量（各来源口径）2026-08-08"""
import duckdb, sqlite3, json, sys

sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
STATE = '/Users/zantao/.hermes/stockdb/state.db'

c = duckdb.connect(TUSHARE, read_only=True)

print("=" * 60)
print("1) stk_factor 直接列（技术因子表）")
cols = c.execute("DESCRIBE SELECT * FROM stk_factor LIMIT 1").fetchall()
col_names = [r[0] for r in cols]
print(f"   总列数: {len(col_names)}")
# 找 extra 列
extra_cols = [n for n in col_names if 'extra' in n.lower()]
print(f"   extra JSON 列: {extra_cols}")
# 去掉 metadata 列后的直接因子列
meta = {'trade_date','ts_code','extra','created_at','update_time'}
direct_factors = [n for n in col_names if n not in meta]
print(f"   直接因子/字段列(含 trade_date/ts_code): {len(direct_factors)}")

# extra JSON 键数量（抽样最新一天一行）
row = c.execute("SELECT extra FROM stk_factor WHERE trade_date=(SELECT MAX(trade_date) FROM stk_factor) AND extra IS NOT NULL LIMIT 1").fetchone()
if row and row[0]:
    try:
        keys = json.loads(row[0])
        print(f"   extra JSON 键数: {len(keys)}")
        # 后缀统计
        from collections import Counter
        suf = Counter()
        for k in keys:
            if k.endswith('_bfq'): suf['_bfq'] += 1
            elif k.endswith('_hfq'): suf['_hfq'] += 1
            elif k.endswith('_qfq'): suf['_qfq'] += 1
            else: suf['其他/裸名'] += 1
        print(f"   后缀分布: {dict(suf)}")
        # 去后缀后的唯一因子名
        base = set()
        for k in keys:
            for s in ('_bfq','_hfq','_qfq'):
                if k.endswith(s):
                    base.add(k[:-len(s)])
                    break
            else:
                base.add(k)
        print(f"   去后缀唯一因子名: {len(base)}")
    except Exception as e:
        print(f"   extra 解析失败: {e}")

print("=" * 60)
print("2) 三因子表 new_factors / flow_alpha / vol_adj")
for t in ['new_factors','flow_alpha','vol_adj']:
    try:
        tcols = c.execute(f"DESCRIBE SELECT * FROM {t} LIMIT 1").fetchall()
        print(f"   {t}: {len(tcols)} 列 -> {[r[0] for r in tcols]}")
    except Exception as e:
        print(f"   {t}: 不存在或错误 {e}")

print("=" * 60)
print("3) factor_group_ic_daily 因子分组（IC 监控口径）")
s = sqlite3.connect(STATE)
try:
    groups = s.execute("SELECT DISTINCT factor_name FROM factor_group_ic_daily").fetchall()
    print(f"   因子分组数: {len(groups)}")
    for g in groups:
        print(f"     - {g[0]}")
except Exception as e:
    print(f"   factor_group_ic_daily: {e}")

print("=" * 60)
print("4) factor_ic_roll 里的 factor_name（滚动 IC 口径）")
try:
    fr = s.execute("SELECT DISTINCT factor_name FROM factor_ic_roll").fetchall()
    print(f"   因子名数: {len(fr)}")
    for r_ in fr:
        print(f"     - {r_[0]}")
except Exception as e:
    print(f"   factor_ic_roll: {e}")

print("=" * 60)
print("5) 模型特征维度（训练用）")
try:
    from core import features
    pv = getattr(features, 'PV_INDICES', None)
    print(f"   features.PV_INDICES: {len(pv) if pv else 'N/A'}")
except Exception as e:
    print(f"   core.features: {e}")
try:
    sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
    import feat_tushare
    n = getattr(feat_tushare, 'compute_features', None)
    print(f"   feat_tushare.compute_features: 存在" if n else "   feat_tushare.compute_features: 无")
except Exception as e:
    print(f"   feat_tushare: {e}")

print("=" * 60)
print("6) stk_factor 最新交易日 & 行数")
r = c.execute("SELECT MAX(trade_date), COUNT(DISTINCT trade_date) FROM stk_factor").fetchone()
print(f"   最新日: {r[0]}, 历史交易日数: {r[1]}")
c.close(); s.close()
