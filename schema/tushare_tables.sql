-- tushare.db 关键表 DDL 2026-09-25 基线（DuckDB；stock_daily 若系 VIEW 见 duckdb_views）
CREATE TABLE adj_factor(ts_code VARCHAR, trade_date VARCHAR, adj_factor DOUBLE, PRIMARY KEY(ts_code, trade_date));;
CREATE TABLE forecast(ts_code VARCHAR, end_date VARCHAR, ann_date VARCHAR, "type" VARCHAR, p_change_min VARCHAR, p_change_max VARCHAR, profit_min VARCHAR, profit_max VARCHAR, last_parent_net VARCHAR, f_ann_date VARCHAR, UNIQUE(ts_code, end_date));;
CREATE TABLE fund_basic(ts_code VARCHAR PRIMARY KEY, "name" VARCHAR, fund_type VARCHAR, list_date VARCHAR, found_date VARCHAR, market VARCHAR, invest_type VARCHAR);;
CREATE TABLE fund_daily(ts_code VARCHAR, trade_date VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, "close" DOUBLE, pre_close DOUBLE, change DOUBLE, pct_chg DOUBLE, vol DOUBLE, amount DOUBLE, PRIMARY KEY(ts_code, trade_date));;
CREATE TABLE repurchase(ts_code VARCHAR, ann_date VARCHAR, end_date VARCHAR, "month" VARCHAR);;
CREATE TABLE stock_basic(ts_code VARCHAR, symbol VARCHAR, "name" VARCHAR, area VARCHAR, industry VARCHAR, market VARCHAR, list_date VARCHAR, delist_date VARCHAR, is_hs VARCHAR, PRIMARY KEY(ts_code));;
CREATE VIEW stock_daily AS SELECT split_part(ts_code, '.', 1) AS stock_code, CAST(strptime("replace"(trade_date, '-', ''), '%Y%m%d') AS DATE) AS date, open, high, low, "close", amount, CAST((vol * 100) AS BIGINT) AS volume, pct_chg AS change_pct, round((((high - low) / "nullif"(pre_close, 0)) * 100), 2) AS amplitude, 0.0 AS turn_rate FROM daily;;
