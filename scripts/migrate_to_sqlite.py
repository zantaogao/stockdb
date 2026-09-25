#!/usr/bin/env python3
"""
tushare.db (DuckDB, 63GB) → tushare_sqlite.db (SQLite)
===========================================================
逐表迁移，批量 INSERT，自动建索引。

只迁移代码实际使用的表（跳过空表/无用表）。

用法:
  python3 scripts/migrate_tushare_to_sqlite.py
"""
import os, sys, time, sqlite3
from pathlib import Path

import duckdb
import numpy as np

BASE = Path.home() / '.hermes' / 'stockdb'
DUCK_PATH = str(BASE / 'tushare.db')
SQLITE_PATH = str(BASE / 'tushare_sqlite.db')

# 需要迁移的表（按代码实际查询频率排序）
# (DuckDB表名, SQLite CREATE TABLE DDL, 行数预估)
TABLES = [
    # ── 核心K线 ──
    ('daily', """
        CREATE TABLE IF NOT EXISTS daily (
            ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL,
            close REAL, pre_close REAL, change REAL, pct_chg REAL,
            vol REAL, amount REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    # ── 每日基本面 ──
    ('daily_basic', """
        CREATE TABLE IF NOT EXISTS daily_basic (
            ts_code TEXT, trade_date TEXT, close REAL, turnover_rate REAL,
            turnover_rate_f REAL, volume_ratio REAL, pe REAL, pe_ttm REAL,
            pb REAL, ps REAL, ps_ttm REAL, dv_ratio REAL, dv_ttm REAL,
            total_share REAL, float_share REAL, free_share REAL,
            total_mv REAL, circ_mv REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    # ── 复权因子 ──
    ('adj_factor', """
        CREATE TABLE IF NOT EXISTS adj_factor (
            ts_code TEXT, trade_date TEXT, adj_factor REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    # ── 资金流 ──
    ('moneyflow_raw', """
        CREATE TABLE IF NOT EXISTS moneyflow_raw (
            ts_code TEXT, trade_date TEXT, buy_sm_vol REAL, buy_sm_amount REAL,
            sell_sm_vol REAL, sell_sm_amount REAL, buy_md_vol REAL,
            buy_md_amount REAL, sell_md_vol REAL, sell_md_amount REAL,
            buy_lg_vol REAL, buy_lg_amount REAL, sell_lg_vol REAL,
            sell_lg_amount REAL, buy_elg_vol REAL, buy_elg_amount REAL,
            sell_elg_vol REAL, sell_elg_amount REAL, net_mf_vol REAL,
            net_mf_amount REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    # ── 技术因子 ──
    ('stk_factor', """
        CREATE TABLE IF NOT EXISTS stk_factor (
            ts_code TEXT, trade_date TEXT,
            open REAL, high REAL, low REAL, close REAL,
            pre_close REAL, change REAL, pct_chg REAL,
            vol REAL, amount REAL,
            macd_dif REAL, macd_dea REAL, macd REAL,
            kdj_k REAL, kdj_d REAL, kdj_j REAL,
            rsi_6 REAL, rsi_12 REAL, rsi_24 REAL,
            boll_upper REAL, boll_mid REAL, boll_lower REAL,
            cci REAL, extra TEXT,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    # ── 涨跌停限制 ──
    ('stk_limit', """
        CREATE TABLE IF NOT EXISTS stk_limit (
            ts_code TEXT, trade_date TEXT, up_limit REAL, down_limit REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    # ── 财务指标 ──
    ('fina_indicator', """
        CREATE TABLE IF NOT EXISTS fina_indicator (
            ts_code TEXT, end_date TEXT, ann_date TEXT,
            eps REAL, dt_eps REAL, total_revenue_ps REAL,
            revenue_ps REAL, capital_reserve_ps REAL,
            surplus_reserve_ps REAL, undistributed_ps REAL,
            extra_item REAL, profit_dedt REAL,
            gross_margin REAL, current_ratio REAL,
            quick_ratio REAL, cash_ratio REAL,
            invturn_days REAL, arturn_days REAL,
            inv_turnover REAL, ar_turnover REAL,
            ca_turnover REAL, fa_turnover REAL,
            assets_turnover REAL, op_income REAL,
            valuechange_income REAL, interst_income REAL,
            daa REAL, ebit REAL, ebitda REAL,
            fcff REAL, fcfe REAL,
            -- 以上是常用字段
            PRIMARY KEY (ts_code, end_date)
        )
    """, 'ts_code, end_date'),
    
    # ── 利润表 ──
    ('fin_income', """
        CREATE TABLE IF NOT EXISTS fin_income (
            ts_code TEXT, end_date TEXT, ann_date TEXT,
            f_ann_date TEXT, report_type TEXT, comp_type TEXT,
            end_type TEXT, revenue TEXT, revenue_yoy TEXT,
            profit TEXT, profit_yoy TEXT, gross_margin TEXT,
            net_margin TEXT, eps TEXT, roe TEXT,
            PRIMARY KEY (ts_code, end_date, report_type)
        )
    """, 'ts_code, end_date'),
    
    # ── 股票基本信息 ──
    ('stock_basic', """
        CREATE TABLE IF NOT EXISTS stock_basic (
            ts_code TEXT, symbol TEXT, name TEXT, area TEXT,
            industry TEXT, fullname TEXT, enname TEXT,
            market TEXT, exchange TEXT, curr_type TEXT,
            list_status TEXT, list_date TEXT, delist_date TEXT,
            is_hs TEXT,
            PRIMARY KEY (ts_code)
        )
    """, 'ts_code'),
    
    # ── 板块行情 ──
    ('board_daily', """
        CREATE TABLE IF NOT EXISTS board_daily (
            ts_code TEXT, trade_date TEXT, board_code TEXT,
            board_name TEXT, open REAL, high REAL, low REAL,
            close REAL, pre_close REAL, pct_chg REAL,
            PRIMARY KEY (board_code, trade_date)
        )
    """, 'board_code, trade_date'),
    
    # ── 其他常用表 ──
    ('weekly', """
        CREATE TABLE IF NOT EXISTS weekly (
            ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL,
            close REAL, pre_close REAL, change REAL, pct_chg REAL,
            vol REAL, amount REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    ('monthly', """
        CREATE TABLE IF NOT EXISTS monthly (
            ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL,
            close REAL, pre_close REAL, change REAL, pct_chg REAL,
            vol REAL, amount REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
    
    ('index_daily_raw', """
        CREATE TABLE IF NOT EXISTS index_daily_raw (
            ts_code TEXT, trade_date TEXT, open REAL, high REAL, low REAL,
            close REAL, pre_close REAL, change REAL, pct_chg REAL,
            vol REAL, amount REAL,
            PRIMARY KEY (ts_code, trade_date)
        )
    """, 'ts_code, trade_date'),
]


def migrate_table(ddb, sdb, table_name, ddl, pk_cols, batch_size=5000):
    """迁移单张表"""
    # 检查 DuckDB 中是否有该表
    try:
        cnt = ddb.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()[0]
    except Exception as e:
        print(f'  {table_name}: ❌ 不存在或无法读取 ({e})')
        return 0
    
    print(f'  {table_name}: {cnt:,} 行...', end=' ', flush=True)
    
    # 建表
    sdb.execute(ddl)
    
    # 获取所有列名
    cols = [r[0] for r in ddb.execute(f"PRAGMA table_info('{table_name}')").fetchall()]
    col_str = ', '.join(f'"{c}"' for c in cols)
    placeholders = ', '.join(['?'] * len(cols))
    
    # 逐批读取 + 写入
    offset = 0
    total = 0
    start = time.time()
    
    while offset < cnt:
        rows = ddb.execute(
            f'SELECT * FROM "{table_name}" ORDER BY {pk_cols} LIMIT {batch_size} OFFSET {offset}'
        ).fetchall()
        if not rows:
            break
        
        # 转换：DuckDB 返回的可能是 numpy 类型，转原生 Python
        cleaned = []
        for row in rows:
            cleaned.append(tuple(None if isinstance(v, float) and np.isnan(v) else
                                 float(v) if isinstance(v, (np.floating,)) else
                                 int(v) if isinstance(v, (np.integer,)) else v
                                 for v in row))
        
        sdb.executemany(
            f'INSERT OR IGNORE INTO "{table_name}" ({col_str}) VALUES ({placeholders})',
            cleaned
        )
        sdb.commit()
        
        offset += batch_size
        total += len(cleaned)
        
        elapsed = time.time() - start
        rate = total / elapsed if elapsed > 0 else 0
        print(f'\r  {table_name}: {total:,}/{cnt:,} 行 ({rate:.0f}行/秒)...', end='', flush=True)
    
    # 建索引
    sdb.execute(f'CREATE INDEX IF NOT EXISTS idx_{table_name}_ts ON "{table_name}" (ts_code)')
    if 'trade_date' in pk_cols:
        sdb.execute(f'CREATE INDEX IF NOT EXISTS idx_{table_name}_date ON "{table_name}" (trade_date)')
    sdb.commit()
    
    elapsed = time.time() - start
    print(f' ✅ {elapsed:.0f}秒')
    return total


def main():
    t0 = time.time()
    
    # 连接 DuckDB（源）
    if not os.path.exists(DUCK_PATH):
        print(f'❌ DuckDB 文件不存在: {DUCK_PATH}')
        sys.exit(1)
    
    ddb = duckdb.connect(DUCK_PATH, read_only=True)
    
    # 创建 SQLite（目标）
    if os.path.exists(SQLITE_PATH):
        bak = SQLITE_PATH + '.bak'
        os.rename(SQLITE_PATH, bak)
        print(f'旧 SQLite 已备份为: {bak}')
    
    sdb = sqlite3.connect(SQLITE_PATH)
    sdb.execute('PRAGMA journal_mode=WAL')
    sdb.execute('PRAGMA synchronous=NORMAL')
    sdb.execute('PRAGMA cache_size=-80000')  # 80MB cache
    print(f'目标: {SQLITE_PATH}')
    
    total_rows = 0
    for table_name, ddl, pk_cols in TABLES:
        n = migrate_table(ddb, sdb, table_name, ddl, pk_cols)
        total_rows += n
    
    # 创建 stock_valuation 视图（同 DuckDB）
    sdb.execute("""
        CREATE VIEW IF NOT EXISTS stock_valuation AS
        SELECT ts_code as stock_code, trade_date as date,
               pe as pe, pe_ttm, pb, ps, pcf,
               total_mv, circ_mv, 0 as dividend_yield
        FROM daily_basic
    """)
    
    # 创建 money_flow 视图
    sdb.execute("""
        CREATE VIEW IF NOT EXISTS money_flow AS
        SELECT ts_code, trade_date, 
               buy_sm_amount as buy_sm_vol, sell_sm_amount as sell_sm_vol,
               buy_md_amount as buy_md_vol, sell_md_amount as sell_md_vol,
               buy_lg_amount as buy_lg_vol, sell_lg_amount as sell_lg_vol,
               buy_elg_amount as buy_elg_vol, sell_elg_amount as sell_elg_vol,
               net_mf_amount as net_mf_vol
        FROM moneyflow_raw
    """)
    
    sdb.commit()
    sdb.close()
    ddb.close()
    
    total_time = time.time() - t0
    size = os.path.getsize(SQLITE_PATH) / 1e9
    print(f'\n{"="*55}')
    print(f'迁移完成!')
    print(f'  总行数: {total_rows:,}')
    print(f'  文件大小: {size:.1f} GB')
    print(f'  耗时: {total_time/60:.0f} 分钟')
    print(f'\n下一步:')
    print(f'  1. 更新 core/db.py 指向 tushare_sqlite.db')
    print(f'  2. 更新 scripts/feat_tushare.py 使用 core.db.get_tushare_db()')


if __name__ == '__main__':
    main()
