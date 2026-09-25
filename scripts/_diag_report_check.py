#!/usr/bin/env python3
"""验证风控距离计算 + 查 CMMR 信号分布（诊断用，不写库）"""
import sqlite3, duckdb

BASE = '/Users/zantao/.hermes/stockdb'
s = sqlite3.connect(f'{BASE}/state.db')
t = duckdb.connect(f'{BASE}/tushare.db', read_only=True)

print('=== 600963 风控距离复现 ===')
# holdings
for r in s.execute("SELECT code, name, avg_cost, shares, stop_loss FROM holdings WHERE code='600963' AND status='hold'").fetchall():
    print('holdings:', r)
# position_peaks
for r in s.execute("SELECT * FROM position_peaks WHERE code='600963'").fetchall():
    print('peaks:', r)
# daily close
for r in t.execute("SELECT trade_date, close FROM daily WHERE ts_code='600963.SH' ORDER BY trade_date DESC LIMIT 3").fetchall():
    print('daily:', r)
ac = 3.13
pk = 3.43
close = 3.34
line = pk * 0.92
print(f'手算: peak={pk} >= 1.05*{ac}={1.05*ac} -> {pk >= 1.05*ac}, 止盈线={line:.4f}, 距离={(close/line-1)*100:+.2f}%')

print()
print('=== 全部持仓 风控距离 复算（对照报告输出） ===')
peaks = {r[0]: float(r[1]) for r in s.execute("SELECT code, peak_price FROM position_peaks").fetchall()}
rows = s.execute("SELECT code, shares, avg_cost, buy_date FROM holdings WHERE status='hold'").fetchall()
for code, shares, ac, bd in rows:
    tc = f'{code}.SH' if code.startswith(('6','68','9')) else f'{code}.SZ'
    r = t.execute("SELECT close FROM daily WHERE trade_date='20260806' AND ts_code=?", [tc]).fetchone()
    if not r or not r[0]:
        continue
    close = float(r[0])
    slv = s.execute("SELECT stop_loss FROM holdings WHERE code=? AND status='hold'", (code,)).fetchone()
    sl = float(slv[0] or 0) if slv else 0
    if not sl or sl <= 0:
        sl = ac * 0.88
    dists = [('止损', (close/sl-1)*100)]
    pk = peaks.get(code)
    if pk and ac and ac > 0 and pk >= 1.05*ac:
        line = pk * 0.92
        dists.append(('止盈线', (close/line-1)*100))
    for kind, d in dists:
        if d < 8:
            print(f'  {code} {kind}: close={close} sl_or_line基准 -> 距 {d:+.1f}%  (peak={pk}, ac={ac})')

print()
print('=== signal_history 20260806 CMMR 分布 ===')
for r in s.execute("""SELECT 
    SUM(CASE WHEN cmmr_score>0 THEN 1 ELSE 0 END),
    COUNT(*),
    MAX(cmmr_score),
    SUM(CASE WHEN fusion_score_cmmr>0 THEN 1 ELSE 0 END)
    FROM signal_history WHERE REPLACE(date,'-','')='20260806'""").fetchall():
    print('cmmr>0 / total / max / cmmr+>0:', r)
print('cmmr_score top15:')
for r in s.execute("""SELECT stock_code, ROUND(cmmr_score,1) FROM signal_history
    WHERE REPLACE(date,'-','')='20260806' AND cmmr_score>0 ORDER BY cmmr_score DESC LIMIT 15""").fetchall():
    print('  ', r)
print('fusion_score_cmmr top15:')
for r in s.execute("""SELECT stock_code, ROUND(fusion_score_cmmr,2) FROM signal_history
    WHERE REPLACE(date,'-','')='20260806' AND fusion_score_cmmr>0 ORDER BY fusion_score_cmmr DESC LIMIT 15""").fetchall():
    print('  ', r)
