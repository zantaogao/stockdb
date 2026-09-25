#!/usr/bin/env python3
"""Cron 校验: cmmr_backtest 样本量 + 信号源对照 (临时脚本, 留原地)"""
import sqlite3

c = sqlite3.connect('state.db')
c.row_factory = sqlite3.Row

print('=== 样本量检查 (有无骤降) ===')
for r in c.execute('''SELECT signal_date, cmmr_n, cmmr80_n, fsc_n
    FROM cmmr_backtest ORDER BY signal_date'''):
    print(dict(r))

print()
print('=== signal_history 每日信号量对照 (CMMR 候选池) ===')
for r in c.execute('''SELECT REPLACE(date,'-','') AS d, COUNT(*) AS n,
    SUM(CASE WHEN cmmr_score > 0 THEN 1 ELSE 0 END) AS cmmr_pos,
    SUM(CASE WHEN cmmr_score >= 80 THEN 1 ELSE 0 END) AS cmmr80
    FROM signal_history WHERE date IS NOT NULL
    GROUP BY 1 ORDER BY 1 DESC LIMIT 6'''):
    print(dict(r))

print()
print('=== CMMR 分数分布 (最新日 20260731) ===')
for r in c.execute('''SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN cmmr_score > 0 THEN 1 ELSE 0 END) AS gt0,
    SUM(CASE WHEN cmmr_score >= 80 THEN 1 ELSE 0 END) AS ge80,
    AVG(cmmr_score) AS avg_s,
    MIN(cmmr_score) AS min_s,
    MAX(cmmr_score) AS max_s
    FROM signal_history WHERE REPLACE(date,'-','') = '20260731' '''):
    print(dict(r))

print()
print('=== 前 3 日对照 (是否同一量级) ===')
for r in c.execute('''SELECT REPLACE(date,'-','') AS d,
    COUNT(*) AS total,
    SUM(CASE WHEN cmmr_score > 0 THEN 1 ELSE 0 END) AS gt0,
    SUM(CASE WHEN cmmr_score >= 80 THEN 1 ELSE 0 END) AS ge80
    FROM signal_history
    WHERE REPLACE(date,'-','') IN ('20260728','20260729','20260730')
    GROUP BY 1 ORDER BY 1'''):
    print(dict(r))

c.close()
