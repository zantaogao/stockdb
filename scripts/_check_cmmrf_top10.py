#!/usr/bin/env python3
"""查 7/24 CMMR+ top10 组成（验证 fwd10_top_cmmrf=97.8 是否合理）"""
import sys, sqlite3
from pathlib import Path
import duckdb
sys.path.insert(0, str(Path.home() / '.hermes' / 'stockdb'))
from core.db import TUSHARE_DB_PATH

BASE = Path.home() / '.hermes' / 'stockdb'
c = sqlite3.connect(str(BASE / 'state.db'))

# 执行侧口径：fusion_score_cmmr > 0 的 p85 以上
rows = c.execute("""
    SELECT stock_code, fusion_score_cmmr FROM signal_history
    WHERE REPLACE(date,'-','')='20260724' AND fusion_score_cmmr IS NOT NULL AND fusion_score_cmmr > 0
""").fetchall()
scores = sorted(float(r[1]) for r in rows)
n = len(scores)
p85 = scores[int(n * 0.85)] if n > 0 else 0
picks = sorted([(r[0], float(r[1])) for r in rows if float(r[1]) >= p85], key=lambda x: x[1], reverse=True)
print(f'7/24: fusion_score_cmmr>0 共 {n} 只, p85 阈值 = {p85:.2f}, p85 以上 {len(picks)} 只')
print(f'前 15 只:')
for code, sc in picks[:15]:
    print(f'  {code}  score={sc:.2f}')
c.close()

# 这些股票 7/24 → 8/7 的 10 日收益（w10 窗口）
top10 = [code for code, _ in picks[:10]]
conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
print(f'\n=== top10 的 10 日收益（7/24 → 8/7 附近）===')
rets = []
for code in top10:
    ts = f'{code}.SH' if code.startswith(('6','9')) else f'{code}.SZ'
    px = conn.execute("""
        SELECT trade_date, close FROM daily WHERE ts_code=? 
        AND trade_date IN ('20260724','20260807') ORDER BY trade_date
    """, [ts]).fetchall()
    if len(px) == 2:
        r = (px[1][1] / px[0][1] - 1) * 100
        rets.append(r)
        print(f'  {code}: 7/24={px[0][1]:.2f} → 8/7={px[1][1]:.2f} = {r:+.1f}%')
print(f'\n等权均值: {sum(rets)/len(rets):+.2f}% (n={len(rets)})')
conn.close()
