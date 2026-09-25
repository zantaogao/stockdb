#!/usr/bin/env python3
"""快速初始化stock.db表结构，不拉取任何数据。"""
import os
import duckdb

DB_PATH = os.path.expanduser("~/.hermes/stockdb/stock.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_info (
    stock_code VARCHAR PRIMARY KEY,
    stock_name VARCHAR,
    short_name  VARCHAR,
    industry    VARCHAR,
    board       VARCHAR,
    market      VARCHAR,
    list_date   DATE,
    total_shares DOUBLE,
    float_shares DOUBLE,
    market_cap  DOUBLE,
    float_cap   DOUBLE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stock_daily (
    stock_code VARCHAR,
    date       DATE,
    open       DOUBLE,
    close      DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    volume     BIGINT,
    amount     DOUBLE,
    amplitude  DOUBLE,
    change_pct DOUBLE,
    turn_rate  DOUBLE,
    PRIMARY KEY (stock_code, date)
);

CREATE TABLE IF NOT EXISTS stock_valuation (
    stock_code  VARCHAR,
    date        DATE,
    pe          DOUBLE,
    pe_ttm      DOUBLE,
    pb          DOUBLE,
    ps          DOUBLE,
    pcf         DOUBLE,
    dividend_yield DOUBLE,
    total_mv    DOUBLE,
    PRIMARY KEY (stock_code, date)
);

CREATE TABLE IF NOT EXISTS fin_income (
    stock_code    VARCHAR,
    report_date   DATE,
    revenue       DOUBLE,
    revenue_yoy   DOUBLE,
    profit        DOUBLE,
    profit_yoy    DOUBLE,
    gross_margin  DOUBLE,
    net_margin    DOUBLE,
    eps           DOUBLE,
    roe           DOUBLE,
    PRIMARY KEY (stock_code, report_date)
);

CREATE TABLE IF NOT EXISTS fin_balance (
    stock_code    VARCHAR,
    report_date   DATE,
    total_assets  DOUBLE,
    total_liab    DOUBLE,
    net_assets    DOUBLE,
    cash          DOUBLE,
    debt_ratio    DOUBLE,
    PRIMARY KEY (stock_code, report_date)
);

CREATE TABLE IF NOT EXISTS fin_cashflow (
    stock_code    VARCHAR,
    report_date   DATE,
    operate_cf    DOUBLE,
    invest_cf     DOUBLE,
    finance_cf    DOUBLE,
    free_cf       DOUBLE,
    PRIMARY KEY (stock_code, report_date)
);

CREATE TABLE IF NOT EXISTS industry_board (
    board_code    VARCHAR PRIMARY KEY,
    board_name    VARCHAR,
    board_type    VARCHAR
);

CREATE TABLE IF NOT EXISTS board_daily (
    board_code VARCHAR,
    date       DATE,
    open       DOUBLE,
    close      DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    volume     BIGINT,
    amount     DOUBLE,
    change_pct DOUBLE,
    PRIMARY KEY (board_code, date)
);

CREATE TABLE IF NOT EXISTS dragon_tiger (
    stock_code    VARCHAR,
    trade_date    DATE,
    reason        VARCHAR,
    total_buy     DOUBLE,
    total_sell    DOUBLE,
    net_amount    DOUBLE,
    PRIMARY KEY (stock_code, trade_date)
);

CREATE TABLE IF NOT EXISTS north_flow (
    trade_date DATE PRIMARY KEY,
    sh_net     DOUBLE,
    sz_net     DOUBLE,
    total_net  DOUBLE
);

CREATE TABLE IF NOT EXISTS index_daily (
    index_code VARCHAR,
    date       DATE,
    open       DOUBLE,
    close      DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    volume     BIGINT,
    amount     DOUBLE,
    change_pct DOUBLE,
    PRIMARY KEY (index_code, date)
);

CREATE TABLE IF NOT EXISTS money_flow (
    stock_code VARCHAR,
    date       DATE,
    main_net   DOUBLE,
    retail_net DOUBLE,
    main_pct   DOUBLE,
    PRIMARY KEY (stock_code, date)
);

CREATE TABLE IF NOT EXISTS db_progress (
    table_name  VARCHAR PRIMARY KEY,
    last_update TIMESTAMP,
    row_count   INTEGER,
    status      VARCHAR DEFAULT 'done'
);
"""

def init_db():
    # Remove the corrupted file
    import shutil
    if os.path.exists(DB_PATH):
        print(f"Removing corrupted {DB_PATH} ({os.path.getsize(DB_PATH) / 1024 / 1024:.0f} MB)...")
        os.remove(DB_PATH)
    
    conn = duckdb.connect(DB_PATH)
    for stmt in SCHEMA_SQL.split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.close()
    
    # Check tables
    conn = duckdb.connect(DB_PATH)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"\n✅ Created {len(tables)} tables:")
    for t in tables:
        print(f"   - {t[0]}")
    conn.close()
    print(f"\nDone. DB size: {os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB")

if __name__ == '__main__':
    init_db()
