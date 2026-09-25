#!/usr/bin/env python3
"""全面策略对比: 短线/长线/混合 — 5年全周期"""
import duckdb, os, sys, time
sys.path.insert(0, os.path.expanduser("~/.hermes/stockdb/scripts"))
from importlib import util
spec = util.spec_from_file_location("fupan", os.path.expanduser("~/.hermes/stockdb/scripts/复盘.py"))
fp = util.module_from_spec(spec)
spec.loader.exec_module(fp)

conn = duckdb.connect(os.path.expanduser("~/.hermes/stockdb/stock.db"))
today = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
dates = [d[0] for d in conn.execute(f"""
    SELECT DISTINCT date FROM stock_daily WHERE date >= '2020-01-01' AND date <= '{today}' ORDER BY date
""").fetchall()]

def run_test(label, hold, top_n, mode, style=None, step=None, market_filter=0):
    step = step or max(1, hold // 4)
    trades = []
    for i in range(0, len(dates) - hold, step):
        bd = dates[i]; sd = dates[i+hold]
        bds = bd.isoformat() if hasattr(bd, 'isoformat') else str(bd)
        sds = sd.isoformat() if hasattr(sd, 'isoformat') else str(sd)
        
        # Market filter
        if market_filter:
            r = conn.execute(f"""
                SELECT t.close, (SELECT AVG(close) FROM index_daily WHERE index_code='000001' 
                    AND date >= DATE '{bds}'-INTERVAL '60' DAY AND date < '{bds}') as ma60
                FROM index_daily t WHERE index_code='000001' AND date='{bds}'
            """).fetchone()
            if not r or not r[1] or r[0] < r[1]: continue
        
        if mode == 'long':
            cand = fp.get_candidates_long(conn, bds) or []
        elif mode == 'short':
            cand = fp.get_candidates_short(conn, bds, style=style) or []
        elif mode == 'hybrid':
            long_c = {c['code'] for c in (fp.get_candidates_long(conn, bds) or [])[:20]}
            short_c = {c['code'] for c in (fp.get_candidates_short(conn, bds, style=style) or [])[:20]}
            common = list(long_c & short_c)
            cand = [{'code': c} for c in common]
        else:
            continue
        
        for c in cand[:top_n]:
            code = c['code']
            buy = conn.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' AND date='{bds}'").fetchone()
            sell = conn.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' AND date='{sds}'").fetchone()
            if not buy or not sell or sell[0] <= 0: continue
            trades.append((sell[0] - buy[0]) / buy[0] * 100)
    
    if not trades: return None
    wins = sum(1 for r in trades if r > 0)
    return {'label': label, 'win_rate': wins/len(trades)*100, 'avg': sum(trades)/len(trades),
            'trades': len(trades), 'med': sorted(trades)[len(trades)//2]}

tests = [
    # 短线基准
    (10, 5, 'short', 'reversal', '短线 reversal 10d'),
    (10, 5, 'short', 'breakout', '短线 breakout 10d'),
    
    # 长线基准
    (60, 5, 'long', None, '长线 TOP5 60d'),
    (90, 3, 'long', None, '长线 TOP3 90d'),
    (90, 5, 'long', None, '长线 TOP5 90d'),
    (120, 3, 'long', None, '长线 TOP3 120d'),
    (120, 5, 'long', None, '长线 TOP5 120d'),
    
    # 长线+市场择时
    (90, 5, 'long', None, '长线TOP5 90d+择时', 1),
    (90, 3, 'long', None, '长线TOP3 90d+择时', 1),
    (120, 3, 'long', None, '长线TOP3 120d+择时', 1),
    
    # 混合: 基本面+短线信号
    (90, 3, 'hybrid', 'reversal', '基本面+超跌 TOP3 90d'),
    (90, 5, 'hybrid', 'reversal', '基本面+超跌 TOP5 90d'),
    (90, 3, 'hybrid', 'breakout', '基本面+突破 TOP3 90d'),
    (120, 3, 'hybrid', 'reversal', '基本面+超跌 TOP3 120d'),
]

print("=" * 80)
print("全面策略对比 (2020-2026, 5年全周期)")
print("=" * 80)
print(f"{'策略':<26} {'胜率':>6} {'均收':>8} {'中位':>8} {'交易':>5}")
print("-" * 80)

results = []
for t in tests:
    hold, top, mode, style = t[0], t[1], t[2], t[3]
    label = t[4]
    mf = t[5] if len(t) > 5 else 0
    r = run_test(label, hold, top, mode, style, market_filter=mf)
    if r:
        emoji = "🟢" if r['win_rate'] >= 55 else "🔴"
        print(f"{emoji} {r['label']:<24} {r['win_rate']:>5.1f}% {r['avg']:>+7.2f}% {r['med']:>+7.2f}% {r['trades']:>5}")
        results.append(r)

print()
print("=" * 80)
print("🏆 按胜率排名 (≥55%为绿)")
print("-" * 80)
for i, r in enumerate(sorted(results, key=lambda x: -x['win_rate']), 1):
    emoji = "🟢" if r['win_rate'] >= 55 else "🔴"
    print(f"  #{i:>2} {emoji} {r['label']:<24} {r['win_rate']:>5.1f}% {r['avg']:>+7.2f}% {r['trades']:>5}次")

conn.close()
