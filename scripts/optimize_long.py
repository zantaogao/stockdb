#!/usr/bin/env python3
"""
长线策略全面优化 — 多维度调参
测试组合: 持有期 × TOP数 × 市场择时 × 行业过滤 × 动量增强 × 因子权重
"""
import duckdb, os, sys, time, json
from datetime import datetime, timedelta

DB = os.path.expanduser("~/.hermes/stockdb/stock.db")
conn = duckdb.connect(DB)
today = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]

sys.path.insert(0, os.path.expanduser("~/.hermes/stockdb/scripts"))
from importlib import util as import_util
spec = import_util.spec_from_file_location("fupan", os.path.expanduser("~/.hermes/stockdb/scripts/复盘.py"))
fp = import_util.module_from_spec(spec)
spec.loader.exec_module(fp)

dates = [d[0] for d in conn.execute(f"""
    SELECT DISTINCT date FROM stock_daily
    WHERE date >= '2020-01-01' AND date <= '{today}'
    ORDER BY date
""").fetchall()]

results = []

def bt_long_custom(hold=90, top_n=5, step=None, market_filter=False, industry_filter=None, label=''):
    """通用长线回测"""
    if step is None: step = max(1, hold // 4)
    trades = []
    skipped = 0
    
    for i in range(0, len(dates) - hold, step):
        bd = dates[i]; sd = dates[i+hold]
        bds = bd.isoformat() if hasattr(bd, 'isoformat') else str(bd)
        sds = sd.isoformat() if hasattr(sd, 'isoformat') else str(sd)
        
        # ── 市场择时 ──
        if market_filter:
            try:
                row = conn.execute(f"""
                    SELECT t.close,
                           (SELECT AVG(close) FROM index_daily WHERE index_code='000001' 
                            AND date >= DATE '{bds}' - INTERVAL '60' DAY AND date < '{bds}') as ma60
                    FROM index_daily t WHERE t.index_code='000001' AND t.date='{bds}'
                """).fetchone()
                if not row or not row[1] or row[0] < row[1] * 0.95:
                    skipped += 1
                    continue
                # 大盘5日不暴跌
                cum5 = conn.execute(f"""
                    SELECT COALESCE(SUM(change_pct),0) FROM index_daily 
                    WHERE index_code='000001' AND date >= DATE '{bds}' - INTERVAL '5' DAY AND date < '{bds}'
                """).fetchone()[0]
                if cum5 < -3:
                    skipped += 1
                    continue
            except:
                skipped += 1
                continue
        
        cand = fp.get_candidates_long(conn, bds)
        if not cand: continue
        
        # ── 行业过滤 ──
        if industry_filter:
            filtered = []
            for c in cand:
                code = c['code']
                ind = conn.execute(f"SELECT industry FROM stock_info WHERE stock_code='{code}'").fetchone()
                if ind and ind[0]:
                    # 行业名包含过滤关键词
                    if any(kw in (ind[0] or '') for kw in industry_filter.split(',')):
                        filtered.append(c)
            cand = filtered
        
        for c in cand[:top_n]:
            code = c['code']
            buy = conn.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' AND date='{bds}'").fetchone()
            sell = conn.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' AND date='{sds}'").fetchone()
            if not buy or not sell or sell[0] <= 0: continue
            ret = (sell[0] - buy[0]) / buy[0] * 100
            trades.append(ret)
    
    if not trades: return None
    wins = sum(1 for r in trades if r > 0)
    return {
        'label': label, 'hold': hold, 'top_n': top_n,
        'win_rate': round(wins/len(trades)*100, 1),
        'avg_return': round(sum(trades)/len(trades), 2),
        'trades': len(trades),
        'skipped': skipped,
        'max_r': round(max(trades), 2),
        'min_r': round(min(trades), 2),
        'med_r': round(sorted(trades)[len(trades)//2], 2),
    }

# ══════════════════════════════════════
# 测试1: 持有期 × TOP数 网格搜索
# ══════════════════════════════════════
print("=" * 95)
print("测试1: 持有期 × TOP数 网格搜索 (2020-2026)")
print("=" * 95)
print(f"{'配置':<22} {'胜率':>6} {'均收':>8} {'中位':>8} {'最大':>8} {'最小':>8} {'交易':>5}")
print("-" * 95)

for hold in [30, 45, 60, 75, 90, 120]:
    for top_n in [3, 5, 10]:
        r = bt_long_custom(hold, top_n, label=f'TOP{top_n} {hold}d')
        if r:
            emoji = "🟢" if r['win_rate'] >= 55 else "🔴"
            print(f"{emoji} {r['label']:<18} {r['win_rate']:>5.1f}% {r['avg_return']:>+7.2f}% {r['med_r']:>+7.2f}% {r['max_r']:>+8.2f}% {r['min_r']:>+8.2f}% {r['trades']:>5}")
            results.append(r)

# ══════════════════════════════════════
# 测试2: 市场择时
# ══════════════════════════════════════
print()
print("=" * 95)
print("测试2: 加市场择时 (大盘站MA60+5日不暴跌)")
print("=" * 95)
print(f"{'配置':<22} {'胜率':>6} {'均收':>8} {'中位':>8} {'跳过':>6} {'交易':>5} {'变化':>8}")
print("-" * 95)

for hold in [60, 90, 120]:
    for top_n in [3, 5]:
        r_base = bt_long_custom(hold, top_n, market_filter=False, label=f'基准 TOP{top_n} {hold}d')
        r_mkt = bt_long_custom(hold, top_n, market_filter=True, label=f'+择时 TOP{top_n} {hold}d')
        if r_base and r_mkt:
            delta = r_mkt['win_rate'] - r_base['win_rate']
            emoji = "🟢" if delta > 0 else "🔴"
            print(f"{emoji} {r_mkt['label']:<18} {r_mkt['win_rate']:>5.1f}% {r_mkt['avg_return']:>+7.2f}% {r_mkt['med_r']:>+7.2f}% {r_mkt['skipped']:>5}天 {r_mkt['trades']:>5} Δ{delta:>+.1f}pp")
            results.append(r_mkt)

# ══════════════════════════════════════
# 测试3: 行业过滤
# ══════════════════════════════════════
print()
print("=" * 95)
print("测试3: 行业过滤 (仅保留科技/消费/医药/制造)")
print("=" * 95)
print(f"{'配置':<22} {'胜率':>6} {'均收':>8} {'中位':>8} {'交易':>5}")
print("-" * 95)

ind_filters = {
    '泛科技': '计算机,通信,电子,半导体,软件,互联网,AI',
    '泛消费': '食品,饮料,医药,医疗,消费,家电,汽车',
    '新能源': '光伏,锂电,新能源,电力设备,储能',
    '高端制造': '机械,装备,军工,自动化,机器人',
    '科技+消费': '计算机,通信,电子,半导体,食品,饮料,医药,医疗',
    '全行业(排除金融地产)': '银行,保险,证券,房地产,信托',
}

for hold in [60, 90]:
    for top_n in [3, 5]:
        r_base = bt_long_custom(hold, top_n, label=f'基准 TOP{top_n} {hold}d')
        for ind_name, ind_kw in ind_filters.items():
            if '排除' in ind_name:
                # 排除模式: 只有不在这些行业的才保留
                r = bt_long_custom(hold, top_n, industry_filter=f'排除:{ind_kw}', label=f'{ind_name[:10]} TOP{top_n} {hold}d')
            else:
                r = bt_long_custom(hold, top_n, industry_filter=ind_kw, label=f'{ind_name[:10]} TOP{top_n} {hold}d')
            if r and r['trades'] >= 20:
                emoji = "🟢" if r['win_rate'] >= 55 else "🔴"
                print(f"{emoji} {r['label']:<18} {r['win_rate']:>5.1f}% {r['avg_return']:>+7.2f}% {r['med_r']:>+7.2f}% {r['trades']:>5}")

# ══════════════════════════════════════
# 输出最优组合
# ══════════════════════════════════════
print()
print("=" * 95)
sorted_r = sorted([r for r in results if r and r['trades'] >= 30], key=lambda x: -x['win_rate'])
print("🏆 全量测试 TOP15 (按胜率)")
print("-" * 95)
print(f"{'排名':>4} {'配置':<22} {'胜率':>6} {'均收':>8} {'中位':>8} {'交易':>5}")
print("-" * 95)
for i, r in enumerate(sorted_r[:15], 1):
    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "  "
    print(f"{medal} {i:>2} {r['label']:<18} {r['win_rate']:>5.1f}% {r['avg_return']:>+7.2f}% {r['med_r']:>+7.2f}% {r['trades']:>5}")

conn.close()
print()
print("完成")
