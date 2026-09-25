#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 盘后深复盘取数（只读）"""
import duckdb, sqlite3, json, os
BASE = os.path.expanduser('~/.hermes/stockdb')
out = {}

tdb = duckdb.connect(os.path.join(BASE, 'tushare.db'), read_only=True)

# 1) 指数近5日
try:
    rows = tdb.execute("""
      SELECT ts_code, trade_date, close, pct_chg FROM index_daily_raw
      WHERE ts_code IN ('000852.SH','000001.SH','000016.SH') AND trade_date >= '20260914'
      ORDER BY ts_code, trade_date
    """).fetchall()
    out['index5'] = rows
except Exception as e:
    out['index5_err'] = str(e)

# 2) 上涨/下跌家数近5日（用 daily 全市场）
try:
    rows = tdb.execute("""
      SELECT trade_date, COUNT(*) FILTER (WHERE pct_chg > 0), COUNT(*) FILTER (WHERE pct_chg < 0),
             COUNT(*) FILTER (WHERE pct_chg = 0), SUM(amount)/1e8
      FROM daily WHERE trade_date >= '20260914' GROUP BY trade_date ORDER BY trade_date
    """).fetchall()
    out['breadth5'] = rows
except Exception as e:
    out['breadth5_err'] = str(e)

# 3) 行业板块近10日（sw_daily_raw join stock_industry_raw）
try:
    rows = tdb.execute("""
      WITH d AS (
        SELECT s.trade_date, s.ts_code, s.pct_chg, b.industry_name
        FROM sw_daily_raw s JOIN stock_industry_raw b ON s.ts_code = b.ts_code
        WHERE s.trade_date >= '20260910'
      ), agg AS (
        SELECT trade_date, industry_name, AVG(pct_chg) apct, COUNT(*) n
        FROM d WHERE industry_name IS NOT NULL AND industry_name != ''
        GROUP BY trade_date, industry_name
      )
      SELECT trade_date, industry_name, ROUND(apct,2), n FROM agg
      QUALIFY ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY apct DESC) <= 8
      ORDER BY trade_date DESC, apct DESC
    """).fetchall()
    out['sw_top10d'] = rows
except Exception as e:
    out['sw_err'] = str(e)

# 4) 板块5日累计排名
try:
    rows = tdb.execute("""
      WITH agg AS (
        SELECT s.industry_name, SUM(s.pct_chg) cum,
               SUM(CASE WHEN s.ap>0 THEN 1 ELSE 0 END) updays, cnt
        FROM (
          SELECT trade_date, ts_code, AVG(pct_chg) apct FROM sw_daily_raw
          WHERE trade_date >= '20260910' GROUP BY trade_date, ts_code
        ) t JOIN stock_industry_raw s ON t.ts_code = s.ts_code
        GROUP BY s.industry_name
      )
      SELECT industry_name, ROUND(cum,2), updays FROM agg ORDER BY cum DESC LIMIT 12
    """).fetchall()
    out['sw_cum5'] = rows
except Exception as e:
    out['sw_cum5_err'] = str(e)

tdb.close()

# 5) 持仓 + watchlist（ledger SQLite）
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
lc.row_factory = sqlite3.Row
try:
    out['holdings'] = [dict(r) for r in lc.execute("SELECT * FROM holdings").fetchall()]
except Exception as e:
    out['holdings_err'] = str(e)
try:
    out['watchlist'] = [dict(r) for r in lc.execute("SELECT * FROM watchlist ORDER BY 1 DESC LIMIT 15").fetchall()]
except Exception as e:
    out['watchlist_err'] = str(e)
try:
    out['bal'] = [dict(r) for r in lc.execute("SELECT * FROM account_balance").fetchall()]
except Exception as e:
    pass
# strategy accounts meta
try:
    cols = [r[1] for r in lc.execute("PRAGMA table_info(strategy_accounts_meta)").fetchall()]
    rows = lc.execute("SELECT * FROM strategy_accounts_meta").fetchall()
    out['sa_meta'] = [dict(zip(cols, r)) for r in rows]
except Exception as e:
    out['sa_meta_err'] = str(e)
lc.close()

# 6) IC 序列
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))
def q(sql):
    try:
        cur = sc.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        return [{'err': str(e)}]
out['ic_daily'] = q("SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 12")
out['fusion_ic'] = q("SELECT * FROM fusion_ic_daily ORDER BY 1 DESC LIMIT 12")
out['dual_ic'] = q("SELECT * FROM center_dual_ic_daily ORDER BY 1 DESC LIMIT 12")
out['ic_window'] = q("SELECT * FROM ic_window ORDER BY 1 DESC LIMIT 30")
sc.close()

print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
