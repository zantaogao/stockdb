#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0924 第八轮：板块明细核查 + 异常值溯源 + 主线板块个股交叉验证"""
import duckdb, os, json
BASE = os.path.expanduser('~/.hermes/stockdb')
tdb = duckdb.connect(BASE + '/tushare.db', read_only=True)
out = {}
# 1) 纺织机械/塑料 0922 异常值溯源
out['outlier_0922'] = tdb.execute("""
  SELECT d.ts_code, b.name, b.industry, d.pct_chg, d.close
  FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
  WHERE d.trade_date='20260922' AND b.industry IN ('纺织机械','塑料') AND d.pct_chg > 15
  ORDER BY d.pct_chg DESC""").fetchall()
# 2) 关注行业 0918-0924 每日
inds = ('房产服务','医疗保健','专用机械','焦炭加工','半导体','元器件','通信设备','全国地产',
        '出版业','红黄酒','机械基件','电器仪表','银行','证券','电力','软件服务','有色金属','钢铁','汽车配件','化工原料')
ph = ','.join(f"'{i}'" for i in inds)
out['watch_inds'] = tdb.execute(f"""
  WITH agg AS (
    SELECT d.trade_date, b.industry ind, AVG(d.pct_chg) apct, COUNT(*) n
    FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
    WHERE d.trade_date>='20260918' AND b.industry IN ({ph}) GROUP BY 1,2)
  SELECT ind, trade_date, ROUND(apct,2), n FROM agg ORDER BY ind, trade_date""").fetchall()
# 3) 主线板块龙头票日线（医药/房产服务）
out['leaders'] = tdb.execute("""
  SELECT d.ts_code, b.name, b.industry, d.trade_date, ROUND(d.pct_chg,2), d.close
  FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
  WHERE d.trade_date>='20260918' AND b.name IN ('中源协和','东宝生物','保利发展','万科A','广宇集团','金地集团','圣诺生物','诚意药业','华兰股份')
  ORDER BY b.name, d.trade_date""").fetchall()
# 4) 全市场成交额近8日
out['amount8'] = tdb.execute("SELECT trade_date, ROUND(SUM(amount)/1e8) FROM daily WHERE trade_date>='20260915' GROUP BY 1 ORDER BY 1").fetchall()
# 5) 20日新高/新低家数（宽度）
out['hi_lo'] = tdb.execute("""
  WITH w AS (SELECT ts_code, trade_date, close,
      MAX(close) OVER (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) mx20
    FROM daily WHERE trade_date>='20260801')
  SELECT trade_date, COUNT(*) FILTER (WHERE close>=mx20 AND trade_date>='20260916') hihi
  FROM w WHERE trade_date>='20260916' GROUP BY 1 ORDER BY 1""").fetchall()
tdb.close()
print(json.dumps(out, ensure_ascii=False, default=str, indent=1))
