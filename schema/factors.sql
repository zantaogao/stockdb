-- factors.db DDL 2026-09-25 基线
CREATE TABLE archive_log (
    id INTEGER PRIMARY KEY, archived_at TEXT DEFAULT (datetime('now','localtime')),
    src_table TEXT, trade_date TEXT, rows INTEGER, note TEXT);
CREATE TABLE flow_alpha(date VARCHAR, stock_code VARCHAR, flow_alpha DOUBLE, vol_ratio DOUBLE, price_dir DOUBLE);
CREATE TABLE new_factors(date VARCHAR, stock_code VARCHAR, ma_decay DOUBLE, momentum_accel DOUBLE);
CREATE TABLE tdx_intraday_feat (
        date INTEGER, code TEXT, market TEXT, n_bars INTEGER,
        open30_ret REAL, tail30_ret REAL, vwap_dev REAL,
        rv_1m REAL, amp_intra REAL, vol_dist_am REAL, vol_dist_tail REAL,
        PRIMARY KEY (date, code));
CREATE TABLE vol_adj(date VARCHAR, stock_code VARCHAR, vol_adj DOUBLE, price_volatility DOUBLE, volume_volatility DOUBLE, price_dir DOUBLE);
