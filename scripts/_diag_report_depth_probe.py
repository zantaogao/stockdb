#!/usr/bin/env python3
"""探查盘后报告可加深维度的数据可用性（只读）"""
import sqlite3, duckdb

BASE = '/Users/zantao/.hermes/stockdb'
state = sqlite3.connect(f'{BASE}/state.db', timeout=30)
tushare = duckdb.connect(f'{BASE}/tushare.db', read_only=True)

print('=== 1. signal_history schema ===')
for r in state.execute("PRAGMA table_info(signal_history)").fetchall():
    print('  ', r[1], r[2])
d3 = str(state.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0])
print('最新信号日:', d3)

print('\n=== 2. 最新日 signal_history 样例（前3行）===')
for r in state.execute(
    "SELECT * FROM signal_history WHERE REPLACE(date,'-','')=? LIMIT 3", (d3,)).fetchall():
    print('  ', r)

print('\n=== 3. 当前持仓 + 最新日评分联动 ===')
holds = state.execute("SELECT code, name, shares, avg_cost, stop_loss, buy_date FROM holdings WHERE status='hold'").fetchall()
print(f'持仓 {len(holds)} 只:')
for code, nm, sh, ac, sl, bd in holds:
    r = state.execute(
        "SELECT fusion_score, final_score, old_score FROM signal_history WHERE REPLACE(date,'-','')=? AND stock_code=?",
        (d3, str(code).split('.')[0])).fetchone()
    print(f'  {code} {nm} 成本{ac} 现持仓{sh} 止损{sl} 买入{bd} | 最新日fusion={r[0] if r else None} final={r[1] if r else None}')

print('\n=== 4. watchlist schema + 最新日 top5 ===')
for r in state.execute("PRAGMA table_info(watchlist)").fetchall():
    print('  ', r[1], r[2])
for r in state.execute(
    "SELECT ts_code, score FROM watchlist WHERE REPLACE(scan_date,'-','')=? ORDER BY score DESC LIMIT 5",
    (d3,)).fetchall():
    print('  ', r)

print('\n=== 5. 中证1000 近10日（风格指标）===')
for r in tushare.execute(
    "SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 10").fetchall():
    print('  ', r)

print('\n=== 6. 近20交易日 涨停数/涨占比（赚钱效应）===')
for r in tushare.execute("""
    SELECT trade_date, COUNT(*) FILTER (WHERE pct_chg>=9.8) AS zt,
           ROUND(100.0*COUNT(*) FILTER (WHERE pct_chg>0)/COUNT(*),1) AS up_pct
    FROM daily WHERE trade_date >= (SELECT MAX(trade_date) FROM daily)::VARCHAR
    GROUP BY 1 ORDER BY 1 DESC LIMIT 20""").fetchall():
    print('  ', r)

print('\n=== 7. ic_daily 近5日 ===')
for r in state.execute("SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 5").fetchall():
    print('  ', r)

print('\n=== 8. backtest 近5日 ===')
for r in state.execute("SELECT signal_date, sb_ew, mkt_ew FROM fusion_3f_backtest ORDER BY signal_date DESC LIMIT 5").fetchall():
    print('  ', r)
for r in state.execute("SELECT signal_date, cmmr_ew, fsc_ew FROM cmmr_backtest ORDER BY signal_date DESC LIMIT 5").fetchall():
    print('  ', r)

state.close(); tushare.close()
