-- ledger.db 全表 DDL 2026-09-25 基线
CREATE TABLE "account_balance" (
"account_id" TEXT,
  "account_name" TEXT,
  "initial_capital" REAL,
  "cash_balance" REAL,
  "total_value" REAL,
  "last_update" TIMESTAMP
);
CREATE TABLE ca_adjustments (
    code TEXT NOT NULL, ex_date TEXT NOT NULL, account TEXT NOT NULL,
    factor REAL DEFAULT 1.0, cash_div REAL DEFAULT 0.0, tax_rate REAL DEFAULT 0.0,
    shares_add INTEGER DEFAULT 0, net_div REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (code, ex_date, account));
CREATE TABLE ca_run_log (
        run_date TEXT PRIMARY KEY,
        status TEXT,
        n_ex INTEGER,
        n_hit INTEGER,
        detail TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );
CREATE TABLE "daban_watch_pool" (
"scan_date" TIMESTAMP,
  "stock_code" TEXT,
  "stock_name" TEXT,
  "industry" TEXT,
  "limit_price" REAL,
  "pct_chg" REAL,
  "circ_mv_yi" REAL,
  "turnover" REAL,
  "open_type" TEXT,
  "signal_sent" INTEGER
);
CREATE TABLE defense_state (mode TEXT PRIMARY KEY, ref_close REAL, set_date TEXT, note TEXT);
CREATE TABLE "execution_logs" (
"exec_id" TEXT,
  "signal_id" TEXT,
  "ts_code" TEXT,
  "direction" TEXT,
  "exec_price" REAL,
  "exec_quantity" INTEGER,
  "exec_time" TIMESTAMP,
  "status" TEXT,
  "error_msg" TEXT
);
CREATE TABLE "holdings" (
"code" TEXT,
  "name" TEXT,
  "status" TEXT,
  "buy_date" TEXT,
  "avg_cost" REAL,
  "shares" INTEGER,
  "latest_price" REAL,
  "pnl" REAL,
  "pnl_pct" REAL,
  "update_time" TEXT
, target_price REAL, stop_loss REAL);
CREATE TABLE holdings_bak_20260828(
  code TEXT,
  name TEXT,
  status TEXT,
  buy_date TEXT,
  avg_cost REAL,
  shares INT,
  latest_price REAL,
  pnl REAL,
  pnl_pct REAL,
  update_time TEXT,
  target_price REAL,
  stop_loss REAL
);
CREATE TABLE position_peaks (
    code TEXT PRIMARY KEY, peak_price REAL, updated_at TEXT);
CREATE TABLE "strategy_accounts_legacy" (
            account_id TEXT NOT NULL,
            date TEXT NOT NULL,
            nav REAL, cash REAL, pos_value REAL,
            daily_ret REAL, market_ret REAL, n_pos INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (account_id, date)
        );
CREATE TABLE strategy_accounts_meta (
                account_id TEXT PRIMARY KEY,
                name TEXT,
                initial_capital REAL,
                cash REAL,
                config_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );
CREATE TABLE strategy_crash_state (
            crash_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE strategy_positions (
                account_id TEXT,
                code TEXT,
                name TEXT,
                shares INTEGER,
                avg_cost REAL,
                buy_date TEXT,
                peak_price REAL,
                stop_loss REAL,
                target REAL,
                total_cost REAL,
                updated_at TEXT,
                PRIMARY KEY (account_id, code)
            );
CREATE TABLE trade_cal (
        cal_date TEXT PRIMARY KEY,   -- YYYYMMDD
        is_open INTEGER NOT NULL,    -- 1=交易日 0=休市
        updated_at TEXT NOT NULL);
CREATE TABLE trade_cooldown (
    code        TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    sell_date   TEXT NOT NULL,      -- 止损出清日 YYYYMMDD
    sell_price  REAL NOT NULL,      -- 止损卖出价（出清加权均价）
    sell_score  REAL,               -- 卖出时信号分
    status      TEXT NOT NULL DEFAULT 'cooldown',  -- cooldown|memory
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (code, strategy)
);
CREATE TABLE "trade_log" (
"id" INTEGER,
  "code" TEXT,
  "name" TEXT,
  "direction" TEXT,
  "price" REAL,
  "quantity" INTEGER,
  "amount" REAL,
  "trade_date" TEXT,
  "trade_time" TEXT,
  "strategy" TEXT,
  "signal_score" REAL,
  "notes" TEXT
);
CREATE TABLE "trade_signals" (
"signal_id" TEXT,
  "ts_code" TEXT,
  "direction" TEXT,
  "price" REAL,
  "quantity" INTEGER,
  "signal_time" TIMESTAMP,
  "status" TEXT
);
CREATE TABLE trade_tp_ban (
    code        TEXT NOT NULL,
    strategy    TEXT NOT NULL,
    sell_date   TEXT NOT NULL,      -- 止盈卖出日 YYYYMMDD
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (code, strategy)
);
CREATE TABLE "watchlist" (
"ts_code" TEXT,
  "score" REAL,
  "scan_date" TIMESTAMP,
  "status" TEXT,
  "created_at" TIMESTAMP
, entry_low REAL DEFAULT 0, entry_high REAL DEFAULT 0, target_price REAL DEFAULT 0, stop_loss REAL DEFAULT 0, source TEXT DEFAULT '');
