#!/usr/bin/env python3
"""
同步 tushare.db 增量数据到 stock.db
=====================================
使用 DuckDB 原生 SQL 批量导入。
支持断点续传：已完成的步骤跳过。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from core.db import TUSHARE_DB_PATH, get_db


def _conn():
    return duckdb.connect(str(STOCK_DB_PATH))


def _ts_conn():
    return duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)


def _table_exists(conn, name):
    row = conn.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema='main' AND table_name = ?
    """, [name]).fetchone()
    return row is not None


def sync_stock_info():
    """同步 stock_basic 新增股票"""
    print("=== 1. 同步 stock_info ===")
    conn = _conn()
    conn.execute(f"ATTACH '{TUSHARE_DB_PATH}' AS ts (READ_ONLY)")

    old_cnt = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]

    conn.execute("""
        INSERT OR REPLACE INTO stock_info 
        (stock_code, stock_name, short_name, industry, board, market, list_date)
        SELECT 
            SPLIT_PART(ts.stock_basic.ts_code, '.', 1),
            ts.stock_basic.name,
            ts.stock_basic.name,
            COALESCE(ts.stock_basic.industry, ''),
            COALESCE(ts.stock_basic.market, ''),
            COALESCE(ts.stock_basic.market, ''),
            CASE 
                WHEN LENGTH(ts.stock_basic.list_date) = 8 
                     AND ts.stock_basic.list_date ~ '^[0-9]{8}$'
                THEN SUBSTR(ts.stock_basic.list_date, 1, 4) || '-' || 
                     SUBSTR(ts.stock_basic.list_date, 5, 2) || '-' || 
                     SUBSTR(ts.stock_basic.list_date, 7, 2)
                ELSE NULL
            END
        FROM ts.stock_basic
        WHERE ts.stock_basic.market IN ('主板', '创业板', '科创板', '北交所')
          AND SPLIT_PART(ts.stock_basic.ts_code, '.', 1) NOT IN (
              SELECT stock_code FROM stock_info
          )
    """)

    new_cnt = conn.execute("SELECT COUNT(*) FROM stock_info").fetchone()[0]
    print(f"  ✅ stock_info: {old_cnt} → {new_cnt} 只股票 (+{new_cnt - old_cnt})")

    conn.execute("DETACH ts")
    conn.close()


def sync_daily():
    """同步缺失的日K数据"""
    print("\n=== 2. 同步日K数据 ===")
    conn = _conn()
    conn.execute(f"ATTACH '{TUSHARE_DB_PATH}' AS ts (READ_ONLY)")

    latest = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    latest_str = str(latest).replace('-', '')
    print(f"  stock_daily 最新: {latest}")

    # 查 tushare 是否有更新的
    newer_cnt = conn.execute("""
        SELECT COUNT(*) FROM ts.daily WHERE trade_date > ?
    """, [latest_str]).fetchone()[0]

    if newer_cnt > 0:
        print(f"  发现 {newer_cnt} 条新日K数据")
        conn.execute(f"""
            INSERT OR REPLACE INTO stock_daily 
            (stock_code, date, open, close, high, low, volume, amount, amplitude, change_pct, turn_rate)
            SELECT 
                SPLIT_PART(d.ts_code, '.', 1),
                SUBSTR(d.trade_date, 1, 4) || '-' || SUBSTR(d.trade_date, 5, 2) || '-' || SUBSTR(d.trade_date, 7, 2),
                d.open, d.close, d.high, d.low,
                CAST(d.vol AS BIGINT), d.amount,
                0.0, d.pct_chg, 0.0
            FROM ts.daily d
            WHERE d.trade_date > '{latest_str}'
        """)
        conn.commit()

    new_latest = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    print(f"  ✅ stock_daily: {total} 条, 最新: {new_latest}")

    conn.execute("DETACH ts")
    conn.close()


def sync_adj_factor():
    """重建 adj_factor 表（全量导入）"""
    print("\n=== 3. 导入 adj_factor ===")
    conn = _conn()
    conn.execute(f"ATTACH '{TUSHARE_DB_PATH}' AS ts (READ_ONLY)")

    # 删除旧的（可能不完整）
    if _table_exists(conn, 'adj_factor'):
        old_cnt = conn.execute("SELECT COUNT(*) FROM adj_factor").fetchone()[0]
        conn.execute("DROP TABLE adj_factor")
        print(f"  删除旧的 adj_factor ({old_cnt} 条，可能不完整)")

    print("  重建 adj_factor...")
    conn.execute("""
        CREATE TABLE adj_factor (
            stock_code VARCHAR,
            date VARCHAR,
            adj_factor DOUBLE
        )
    """)

    conn.execute("""
        INSERT INTO adj_factor (stock_code, date, adj_factor)
        SELECT 
            SPLIT_PART(ts_code, '.', 1),
            trade_date, adj_factor
        FROM ts.adj_factor
    """)
    conn.commit()

    cnt = conn.execute("SELECT COUNT(*) FROM adj_factor").fetchone()[0]
    latest = conn.execute("SELECT MAX(date) FROM adj_factor").fetchone()[0]
    distinct = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM adj_factor").fetchone()[0]
    print(f"  ✅ adj_factor: {cnt} 条, {distinct} 只股票, 最新: {latest}")

    conn.execute("DETACH ts")
    conn.close()


def create_signal_history():
    """创建 signal_history 表"""
    print("\n=== 4. 创建 signal_history 表 ===")
    conn = _conn()

    if _table_exists(conn, 'signal_history'):
        cnt = conn.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0]
        print(f"  signal_history 已存在, {cnt} 条记录")
        conn.close()
        return

    conn.execute("""
        CREATE TABLE signal_history (
            date VARCHAR,
            stock_code VARCHAR,
            fusion_score DOUBLE,
            reg20 DOUBLE,
            reg40 DOUBLE,
            reg10 DOUBLE,
            gtja_score DOUBLE,
            deviation120 DOUBLE,
            PRIMARY KEY (date, stock_code)
        )
    """)
    conn.commit()
    print("  ✅ signal_history 表已创建")
    conn.close()


def sync_moneyflow():
    """同步 tushare moneyflow 到 stock.db"""
    print("\n=== 5. 同步 moneyflow ===")
    conn = _conn()
    conn.execute(f"ATTACH '{TUSHARE_DB_PATH}' AS ts (READ_ONLY)")

    if _table_exists(conn, 'money_flow_full'):
        cnt = conn.execute("SELECT COUNT(*) FROM money_flow_full").fetchone()[0]
        if cnt > 500000:
            print(f"  money_flow_full 已有 {cnt} 条，跳过")
            conn.execute("DETACH ts")
            conn.close()
            return
        else:
            conn.execute("DROP TABLE money_flow_full")
            print(f"  删除不完整的 money_flow_full ({cnt} 条)")

    print("  创建 money_flow_full 表...")
    conn.execute("""
        CREATE TABLE money_flow_full (
            trade_date VARCHAR,
            stock_code VARCHAR,
            buy_sm_amount DOUBLE,
            sell_sm_amount DOUBLE,
            buy_md_amount DOUBLE,
            sell_md_amount DOUBLE,
            buy_lg_amount DOUBLE,
            sell_lg_amount DOUBLE,
            buy_elg_amount DOUBLE,
            sell_elg_amount DOUBLE,
            net_mf_amount DOUBLE,
            net_mf_vol DOUBLE
        )
    """)

    print("  批量导入（DuckDB 原生 SQL）...")
    conn.execute("""
        INSERT INTO money_flow_full 
        (trade_date, stock_code, buy_sm_amount, sell_sm_amount,
         buy_md_amount, sell_md_amount, buy_lg_amount, sell_lg_amount,
         buy_elg_amount, sell_elg_amount, net_mf_amount, net_mf_vol)
        SELECT 
            trade_date, SPLIT_PART(ts_code, '.', 1),
            buy_sm_amount, sell_sm_amount,
            buy_md_amount, sell_md_amount,
            buy_lg_amount, sell_lg_amount,
            buy_elg_amount, sell_elg_amount,
            net_mf_amount, net_mf_vol
        FROM ts.moneyflow
    """)
    conn.commit()

    cnt = conn.execute("SELECT COUNT(*) FROM money_flow_full").fetchone()[0]
    print(f"  ✅ money_flow_full: {cnt} 条")

    conn.execute("DETACH ts")
    conn.close()


def sync_stk_limit():
    """同步涨跌停数据"""
    print("\n=== 6. 同步 stk_limit ===")
    conn = _conn()
    conn.execute(f"ATTACH '{TUSHARE_DB_PATH}' AS ts (READ_ONLY)")

    if _table_exists(conn, 'stk_limit'):
        cnt = conn.execute("SELECT COUNT(*) FROM stk_limit").fetchone()[0]
        if cnt > 100000:
            print(f"  stk_limit 已有 {cnt} 条，跳过")
            conn.execute("DETACH ts")
            conn.close()
            return
        else:
            conn.execute("DROP TABLE stk_limit")
            print(f"  删除不完整的 stk_limit ({cnt} 条)")

    print("  创建 stk_limit 表...")
    conn.execute("""
        CREATE TABLE stk_limit (
            date VARCHAR,
            stock_code VARCHAR,
            up_limit DOUBLE,
            down_limit DOUBLE
        )
    """)

    print("  批量导入...")
    conn.execute("""
        INSERT INTO stk_limit 
        (date, stock_code, up_limit, down_limit)
        SELECT 
            trade_date, SPLIT_PART(ts_code, '.', 1),
            up_limit, down_limit
        FROM ts.stk_limit
    """)
    conn.commit()

    cnt = conn.execute("SELECT COUNT(*) FROM stk_limit").fetchone()[0]
    print(f"  ✅ stk_limit: {cnt} 条")

    conn.execute("DETACH ts")
    conn.close()


def sync_financials():
    """同步财务数据（利润表/资产负债表/现金流量表）"""
    print("\n=== 7. 同步财务数据 ===")
    conn = _conn()
    conn.execute(f"ATTACH '{TUSHARE_DB_PATH}' AS ts (READ_ONLY)")

    for tbl_name in ['fin_income', 'fin_balancesheet', 'fin_cashflow']:
        print(f"  同步 {tbl_name}...")
        ts_tbl = tbl_name
        ts_exists = _table_exists(_ts_conn(), ts_tbl)

        if not ts_exists:
            print(f"    ts.{ts_tbl} 不存在，跳过")
            continue

        # 获取 tushare 表的列名和类型
        desc = conn.execute(f"PRAGMA table_info(ts.{ts_tbl})").fetchall()
        cols_info = [(d[1], d[2]) for d in desc]  # (name, type)
        # 去掉 ts_code
        cols_info = [(n, t) for n, t in cols_info if n != 'ts_code']
        target_names = [c[0] for c in cols_info]
        target_types = [c[1] for c in cols_info]

        # 用 stk_ 前缀
        db_tbl = 'stk_' + tbl_name

        # 删除旧表
        try:
            conn.execute(f"DROP TABLE IF EXISTS {db_tbl}")
        except Exception as e:
            pass

        # 创建新表：每个列都要带类型
        col_defs = ['stock_code VARCHAR'] + [f'"{n}" {t}' for n, t in zip(target_names, target_types)]
        conn.execute(f"CREATE TABLE {db_tbl} ({', '.join(col_defs)})")

        # 批量导入
        src = ["SPLIT_PART(ts_code, '.', 1)"] + [c[0] for c in cols_info]
        conn.execute(f"INSERT INTO {db_tbl} SELECT {', '.join(src)} FROM ts.{ts_tbl}")
        conn.commit()

        cnt = conn.execute(f"SELECT COUNT(*) FROM {db_tbl}").fetchone()[0]
        print(f"    ✅ {db_tbl}: {cnt} 条")

    conn.execute("DETACH ts")
    conn.close()


def sync_valuation():
    """同步估值数据（PE/PB/PS/总市值/流通市值）到 stock_valuation 表"""
    print("\n=== 8. 同步估值数据 (daily_basic) ===")
    conn = _conn()
    conn.execute(f"ATTACH '{TUSHARE_DB_PATH}' AS ts (READ_ONLY)")

    # stock.db 用 stock_valuation, tushare 用 daily_basic
    print("  同步 daily_basic → stock_valuation...")
    if _table_exists(conn, 'stock_valuation'):
        old_cnt = conn.execute("SELECT COUNT(*) FROM stock_valuation").fetchone()[0]
        conn.execute("DROP TABLE stock_valuation")
        print(f"    删除旧表 ({old_cnt} 条)")

    conn.execute("""
        CREATE TABLE stock_valuation (
            stock_code VARCHAR,
            date VARCHAR,
            pe DOUBLE,
            pe_ttm DOUBLE,
            pb DOUBLE,
            ps DOUBLE,
            dv_ratio DOUBLE,
            total_share DOUBLE,
            float_share DOUBLE,
            total_mv DOUBLE,
            circ_mv DOUBLE
        )
    """)

    conn.execute("""
        INSERT INTO stock_valuation
        (stock_code, date, pe, pe_ttm, pb, ps, dv_ratio, total_share, float_share, total_mv, circ_mv)
        SELECT 
            SPLIT_PART(ts_code, '.', 1),
            trade_date, pe, pe_ttm, pb, ps, dv_ratio, total_share, float_share, total_mv, circ_mv
        FROM ts.daily_basic
    """)
    conn.commit()

    cnt = conn.execute("SELECT COUNT(*) FROM stock_valuation").fetchone()[0]
    print(f"  ✅ stock_valuation: {cnt} 条")

    conn.execute("DETACH ts")
    conn.close()


def main():
    print("开始同步 tushare.db → stock.db")
    print(f"  tushare: {TUSHARE_DB_PATH}")
    print(f"  stock:   {STOCK_DB_PATH}")
    print()

    sync_stock_info()
    sync_daily()
    sync_adj_factor()
    create_signal_history()
    sync_moneyflow()
    sync_stk_limit()
    sync_financials()
    sync_valuation()

    print("\n=== 同步完成 ===")

    # 最终验证
    stk = duckdb.connect(str(STOCK_DB_PATH))
    tables = stk.execute("SHOW TABLES").fetchall()
    print(f"\nstock.db 表 ({len(tables)} 个):")
    for t in tables:
        try:
            cnt = stk.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
            print(f"  {t[0]}: {cnt:,}")
        except Exception as e:
            print(f"  {t[0]}: ERROR - {e}")
    stk.close()


if __name__ == '__main__':
    main()
