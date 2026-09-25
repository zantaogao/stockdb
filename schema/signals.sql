-- signals.db DDL 2026-09-25 基线
CREATE TABLE ca_calendar (
        ts_code TEXT, ex_date TEXT, ratio REAL, fake_drop REAL, is_big INTEGER,
        created_at TEXT, PRIMARY KEY (ts_code, ex_date));
CREATE TABLE center_dual_ic_daily (
            date TEXT PRIMARY KEY,
            ic REAL,
            samples INTEGER,
            top_ret REAL,
            bottom_ret REAL,
            ic_diff REAL,
            calc_date TEXT
        , fwd10_top10 REAL, fwd20_top10 REAL, fwd40_top10 REAL);
CREATE TABLE cmmr_backtest (
            signal_date TEXT PRIMARY KEY,
            cmmr_ew REAL, cmmr_n INTEGER, cmmr_win REAL,
            cmmr80_ew REAL, cmmr80_n INTEGER,
            fsc_ew REAL, fsc_n INTEGER, fsc_win REAL,
            mkt_ew REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , cmmr80_top10_ew REAL);
CREATE TABLE cmmr_ic_daily (
        date DATE PRIMARY KEY,
        ic DOUBLE,
        samples INTEGER,
        positive_days INTEGER,
        win_rate DOUBLE
    , forward_days INTEGER);
CREATE TABLE cmmr_top10_ic_daily (
            date TEXT PRIMARY KEY,
            top10_ret REAL, pool_mean REAL, mkt_median REAL,
            excess_pool REAL, excess_mkt REAL, n_pool INTEGER, forward_days INTEGER);
CREATE TABLE cmmr_tp_shadow(
  signal_date TEXT PRIMARY KEY, n INTEGER,
  ret_hold REAL, ret_tp5 REAL, ret_tp3 REAL, tp5_lag INTEGER, tp3_lag INTEGER,
  mkt_hold REAL, mkt_tp5 REAL, mkt_tp3 REAL,
  done INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE etf_ic (
            calc_date DATE NOT NULL,
            signal_date DATE NOT NULL,
            sample_size INTEGER,
            ic_etf DOUBLE,
            top_ret DOUBLE,
            bottom_ret DOUBLE,
            ic_diff DOUBLE, ic_spearman DOUBLE DEFAULT 0, ic_20d DOUBLE DEFAULT 0,
            PRIMARY KEY (calc_date, signal_date)
        );
CREATE TABLE etf_scores (
            ts_code TEXT PRIMARY KEY,
            name TEXT,
            score REAL,
            prediction REAL,
            scan_date TEXT,
            updated_at TEXT
        );
CREATE TABLE factor_group_ic_daily (
            calc_date TEXT, factor_name TEXT, ic REAL, 
            sample_size INTEGER, field_list TEXT,
            PRIMARY KEY (calc_date, factor_name)
        );
CREATE TABLE factor_ic_daily (
            date TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            rank_ic REAL,
            p_value REAL,
            n_stocks INTEGER,
            ret_horizon INTEGER NOT NULL,
            PRIMARY KEY (date, factor_name, ret_horizon)
        );
CREATE TABLE factor_ic_roll (
            factor_name TEXT, as_of_date TEXT, window INTEGER,
            mean_ic REAL, std_ic REAL, icir REAL, win_rate REAL,
            n_days INTEGER, group_name TEXT, max_ic REAL DEFAULT 0, min_ic REAL DEFAULT 0, ret_horizon INTEGER DEFAULT 1, mean_ret REAL, median_ret REAL,
            PRIMARY KEY (factor_name, as_of_date, window)
        );
CREATE TABLE flow_alpha(date VARCHAR, stock_code VARCHAR, flow_alpha DOUBLE, vol_ratio DOUBLE, price_dir DOUBLE);
CREATE TABLE fusion_3f_backtest (
            signal_date TEXT PRIMARY KEY,
            sb_ew REAL, sb_win REAL, n_sb INTEGER,
            mkt_ew REAL, ss_ew REAL, n_ss INTEGER,
            top10_ew REAL, top10_win REAL,
            ls_ret REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE fusion_3f_intraday (
        stock_code TEXT NOT NULL,
        date TEXT NOT NULL,
        scan_time TEXT NOT NULL,
        reg10 REAL,
        ma_decay REAL,
        flow_alpha REAL,
        vol_adj REAL,
        fusion_3f_score REAL,
        base_signal TEXT,
        intraday_signal TEXT,
        change_pct REAL,
        price REAL,
        is_intraday INTEGER DEFAULT 1,
        PRIMARY KEY (stock_code, date, scan_time)
    );
CREATE TABLE fusion_3f_signals (
            stock_code TEXT NOT NULL,
            date TEXT NOT NULL,
            reg10 REAL,
            ma_decay REAL,
            flow_alpha REAL,
            vol_adj REAL,
            fusion_3f_score REAL,
            signal TEXT,
            PRIMARY KEY (stock_code, date)
        );
CREATE TABLE fusion_center_signals (
        date TEXT, stock_code TEXT, stock_name TEXT, industry TEXT,
        score REAL, rank_pct REAL, signal TEXT, PRIMARY KEY (date, stock_code));
CREATE TABLE fusion_ic_daily (
        date DATE PRIMARY KEY,
        ic DOUBLE,
        samples INTEGER,
        positive_days INTEGER,
        win_rate DOUBLE
    , forward_days INTEGER);
CREATE TABLE fx_sentinel_daily (
    date TEXT PRIMARY KEY,        -- YYYYMMDD 自然日
    pmi_mid REAL,                 -- 央行中间价 元/100美元
    usdcny REAL,                  -- 在岸即期（新浪，元）
    cn10y REAL, us10y REAL, us2y REAL,  -- 国债收益率 %
    us_cn_spread REAL,            -- 美10Y - 中10Y（bp 用 %差值，正=倒挂加深方向）
    dxy REAL,                     -- 美元指数
    computed_at TEXT DEFAULT (datetime('now','localtime'))
, usdcnh REAL);
CREATE TABLE ic_daily (
                calc_date DATE,
                signal_date DATE PRIMARY KEY,
                sample_size INTEGER,
                ic_fusion DOUBLE,
                ic_reg20 DOUBLE,
                ic_reg40 DOUBLE,
                ic_reg10 DOUBLE,
                ic_final DOUBLE,
                top_ret DOUBLE,
                bottom_ret DOUBLE,
                ic_diff DOUBLE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            , fwd10 DOUBLE, fwd20 DOUBLE, fwd40 DOUBLE);
CREATE TABLE ic_shadow (
    signal_date TEXT PRIMARY KEY,   -- YYYYMMDD
    n INTEGER, ic_shadow_b REAL, ic_reg10 REAL, ic_fusion REAL,
    computed_at TEXT DEFAULT (datetime('now','localtime')), ic_v4big REAL, ic_v4d REAL, ic_v4e REAL, ic_clf10 REAL, ic_v4f REAL);
CREATE TABLE ic_shadow_442(
  signal_date TEXT PRIMARY KEY, n INTEGER,
  ic_442_clip REAL, ic_442_z REAL, ic_fusion REAL, ic_v4big REAL,
  top10_442_clip REAL, top10_442_z REAL, top10_fusion REAL, bot10_fusion REAL, ic_442_v3 REAL, ic_prod_z REAL, top10_442_v3 REAL, top10_prod_z REAL, bot10_442_z REAL, bot10_442_v3 REAL, bot10_prod_z REAL, mkt10 REAL, ic_r10 REAL, ic_r10r20 REAL, top10_r10 REAL, top10_r10r20 REAL, bot10_r10 REAL, bot10_r10r20 REAL);
CREATE TABLE ic_window (
            signal_date TEXT PRIMARY KEY,
            calc_date TEXT,
            n DOUBLE,
            ic_reg10_w10 DOUBLE,
            ic_reg20_w20 DOUBLE,
            ic_reg40_w40 DOUBLE,
            ic_fusion_w10 DOUBLE,
            ic_fusion_w20 DOUBLE,
            ic_fusion_w40 DOUBLE,
            fwd10_top DOUBLE,
            fwd20_top DOUBLE,
            fwd40_top DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , ic_3f_w10 DOUBLE, ic_cmmr_w10 DOUBLE, ic_cmmrf_w10 DOUBLE, ic_center_w10 DOUBLE, fwd10_top_3f DOUBLE, fwd10_top_cmmr DOUBLE, fwd10_top_cmmrf DOUBLE, fwd10_top_center DOUBLE, fwd10_top_dual DOUBLE, ic_dual_w10 DOUBLE, fwd20_top_cmmrf DOUBLE, fwd40_top_cmmrf DOUBLE, fwd10_top_main DOUBLE, fwd20_top_main DOUBLE, fwd40_top_main DOUBLE, fwd20_top_cmmr DOUBLE);
CREATE TABLE mean_reversion_signals (
                date TEXT,
                stock_code TEXT,
                total_score REAL,
                f1_range REAL,
                f2_flow REAL,
                f3_vol REAL,
                f4_position REAL,
                ma_decay REAL,
                flow_alpha REAL,
                vol_adj REAL,
                close_price REAL,
                PRIMARY KEY (date, stock_code)
            );
CREATE TABLE mf_observer_daily(
  date TEXT, code TEXT, main_net_1d_pct REAL, main_net_5d_pct REAL,
  pos_days_11d INT, elg_net_liq_pct REAL,
  PRIMARY KEY(date, code));
CREATE TABLE mf_observer_ic_daily(
  date TEXT, factor_name TEXT, rank_ic REAL, p_value REAL, n_stocks INT,
  ret_horizon TEXT DEFAULT '5d',
  PRIMARY KEY(date, factor_name));
CREATE TABLE new_factors(date VARCHAR, stock_code VARCHAR, ma_decay DOUBLE, momentum_accel DOUBLE);
CREATE TABLE opinion_feedback (
            date TEXT, code TEXT, type TEXT, price REAL,
            close_t1 REAL, close_t3 REAL,
            ret_t1 REAL, ret_t3 REAL,
            backfilled_at TEXT,
            PRIMARY KEY (date, code, type)
        );
CREATE TABLE shadow_clf10_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code));
CREATE TABLE shadow_v4big_scores (
    date TEXT, code TEXT, score REAL,
    PRIMARY KEY (date, code));
CREATE TABLE shadow_v4d_scores (
    date TEXT, code TEXT, score REAL,
    PRIMARY KEY (date, code));
CREATE TABLE shadow_v4e_scores (
    date TEXT, code TEXT, score REAL,
    PRIMARY KEY (date, code));
CREATE TABLE shadow_v4f_scores (
        date TEXT, code TEXT, score REAL,
        PRIMARY KEY (date, code));
CREATE TABLE "signal_history" (
"date" TEXT,
  "stock_code" TEXT,
  "stock_name" TEXT,
  "industry" TEXT,
  "fusion_score" REAL,
  "reg20" REAL,
  "reg40" REAL,
  "reg10" REAL,
  "gtja_score" REAL,
  "deviation120" REAL,
  "final_score" REAL,
  "fusion_avg" REAL,
  "cls27_prob" REAL,
  "lstm" REAL,
  "reg_pred" REAL,
  "reg10_pred" REAL,
  "reg40_pred" REAL,
  "is_limit_up" INTEGER
, old_score DOUBLE, cmmr_score DOUBLE, ma40_slope DOUBLE, fusion_score_cmmr DOUBLE);
CREATE TABLE signal_shadow (
        date TEXT, stock_code TEXT,
        fusion_cur REAL, fusion_adj REAL,
        reg20_cur REAL, reg20_adj REAL, reg40_cur REAL, reg40_adj REAL,
        pct_cur REAL, pct_adj REAL, final_score_cur REAL,
        is_ca INTEGER, ca_ratio REAL, ca_gap INTEGER,
        created_at TEXT, PRIMARY KEY (date, stock_code));
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE stock_basic (
    stock_code TEXT,
    name TEXT,
    industry TEXT,
    market TEXT,
    list_date TEXT
);
CREATE TABLE tdx_intraday_feat (
        date INTEGER, code TEXT, market TEXT, n_bars INTEGER,
        open30_ret REAL, tail30_ret REAL, vwap_dev REAL,
        rv_1m REAL, amp_intra REAL, vol_dist_am REAL, vol_dist_tail REAL, tail5_ret REAL, last_vol_share REAL,
        PRIMARY KEY (date, code));
CREATE TABLE tdx_signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date TEXT,        -- 记录日期 YYYY-MM-DD
    signal_date TEXT,     -- 信号日(最新交易日) YYYY-MM-DD
    code TEXT,
    signal_type TEXT,     -- low_absorb_wash / low_absorb / normal_buy / excluded_tail / excluded_entrap
    action TEXT,          -- BUY / EXCLUDE
    price REAL,           -- 决策时价格(实时)
    account TEXT,         -- main / fusion3f / cmmr / cmmr_fusion / fusion_center
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE vol_adj(date VARCHAR, stock_code VARCHAR, vol_adj DOUBLE, price_volatility DOUBLE, volume_volatility DOUBLE, price_dir DOUBLE);
