#!/usr/bin/env python3
# ca_calendar 覆盖率体检：近20交易日除权事件总数 vs 评分池命中数（001225 漏报根因定性）
import sqlite3, duckdb
BASE = '/Users/zantao/.hermes/stockdb'
sig = sqlite3.connect(BASE + '/signals.db', timeout=10)
d = duckdb.connect(BASE + '/tushare.db', read_only=True)

# 近20交易日
dates = [r[0] for r in d.execute("SELECT DISTINCT trade_date FROM daily WHERE trade_date>='20260901' ORDER BY trade_date DESC LIMIT 20").fetchall()]
recent = set(dates)
# ca_calendar 在这些日期的除权事件
ev = sig.execute("SELECT ts_code, ex_date, ratio FROM ca_calendar WHERE ex_date IN (%s)" % ','.join('?'*len(recent)), sorted(recent)).fetchall()
print(f'近20交易日({len(recent)}天, {min(recent)}~{max(recent)}) ca_calendar 除权事件: {len(ev)} 条')
# 这些事件有多少进了 signal_shadow（=评分池）
hit = sig.execute("SELECT COUNT(DISTINCT ts_code) FROM ca_calendar c WHERE c.ex_date IN (%s) AND EXISTS (SELECT 1 FROM signal_shadow s WHERE c.ts_code LIKE s.stock_code||'%%' AND s.date='20260924')" % ','.join('?'*len(recent)), sorted(recent)).fetchall()
print('其中在 signal_shadow(0924 池200只) 中:', hit)
# 全市场0924评分池总数（signal_history）
pool = sig.execute("SELECT COUNT(DISTINCT stock_code) FROM signal_history WHERE REPLACE(date,'-','')='20260924'").fetchone()
print('0924 signal_history 全池:', pool)
# 近20日除权事件在全池中的数量
n = sig.execute("SELECT COUNT(DISTINCT c.ts_code) FROM ca_calendar c WHERE c.ex_date IN (%s) AND EXISTS (SELECT 1 FROM signal_history s WHERE c.ts_code LIKE s.stock_code||'%%' AND REPLACE(s.date,'-','')='20260924')" % ','.join('?'*len(recent)), sorted(recent)).fetchone()
print('近20日除权且在今日全池的票:', n)
