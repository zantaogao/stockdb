#!/usr/bin/env python3
"""
CMMR 策略每日 IC 计算
计算两套新策略的 IC 并入库：
- cmmr_ic_daily: CMMR 独立策略 IC
- fusion_ic_daily: CMMR+ 模型融合策略 IC（原名"三因子融合"系误称：old_score=三模型融合分，2026-08-10 更正）
"""
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import sys
import duckdb

STATE_DB = Path.home() / '.hermes' / 'stockdb' / 'signals.db'  # v2温层
TUSHARE_DB = Path.home() / '.hermes' / 'stockdb' / 'tushare.db'

def get_batch_prices(codes, trade_date, forward_days=20):
    """批量获取未来收盘价"""
    try:
        conn = duckdb.connect(str(TUSHARE_DB), read_only=True)
        date_clean = trade_date.replace('-', '')
        ts_codes = [
            f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"
            for c in codes
        ]
        placeholders = ','.join(['?'] * len(ts_codes))
        
        if forward_days == 0:
            rows = conn.execute(f"""
                SELECT ts_code, close FROM daily 
                WHERE trade_date = '{date_clean}'
                AND ts_code IN ({placeholders})
            """, ts_codes).fetchall()
        else:
            # 用窗口函数取第N个交易日
            rows = conn.execute(f"""
                SELECT ts_code, close FROM (
                    SELECT ts_code, close,
                           ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date) as rn
                    FROM daily 
                    WHERE trade_date > '{date_clean}'
                    AND ts_code IN ({placeholders})
                ) WHERE rn = {forward_days}
            """, ts_codes).fetchall()
        
        conn.close()
        return {r[0]: float(r[1]) for r in rows}
    except Exception as e:
        return {}

def calculate_cmmr_fusion_ic(date_str, forward_days=20, forward_days_fusion=None):
    """计算指定日期的 CMMR 独立 + 融合 IC。
    09-20 分窗：cmmr 列用 forward_days（定稿=10，对齐账户 rebalance=10），
    fusion 列用 forward_days_fusion（定稿=20，对齐 cmmr_fusion 账户信号窗 20d）。"""
    fd_f = forward_days if forward_days_fusion is None else forward_days_fusion
    conn = sqlite3.connect(STATE_DB)
    
    try:
        # 1. 读取信号历史（包含 old_score, cmmr_score, fusion_score_cmmr）
        date_clean = date_str.replace('-', '')
        query = f"""
            SELECT stock_code, date, old_score, cmmr_score, fusion_score_cmmr
            FROM signal_history s
            WHERE REPLACE(date, '-', '') = '{date_clean}'
            AND fusion_score_cmmr IS NOT NULL
        """
        df = pd.read_sql_query(query, conn)
        
        if len(df) < 100:
            print(f"样本不足：{len(df)} 只")
            return None, None, len(df), 0, 0
        
        print(f"读取到 {len(df)} 只股票的评分数据")
        
        # 2. 批量获取未来收盘价 + 当前收盘价（cmmr/fusion 两列各自窗口，09-20 分窗）
        codes = df['stock_code'].tolist()
        print(f"批量获取未来 {forward_days}/{fd_f} 日收盘价 ({len(codes)} 只)...")
        future_map = get_batch_prices(codes, date_str, forward_days=forward_days)
        future_map_f = (future_map if fd_f == forward_days
                        else get_batch_prices(codes, date_str, forward_days=fd_f))
        print(f"批量获取当前收盘价 ({len(codes)} 只)...")
        current_map = get_batch_prices(codes, date_str, forward_days=0)
        
        # 3. 合并
        df['ts_code'] = df['stock_code'].apply(
            lambda c: f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ"
        )
        df['future_close'] = df['ts_code'].map(future_map)
        df['future_close_f'] = df['ts_code'].map(future_map_f)
        df['current_close'] = df['ts_code'].map(current_map)
        df = df.dropna(subset=['future_close', 'future_close_f', 'current_close'])
        
        print(f"有效样本：{len(df)} 只")
        
        if len(df) < 100:
            print(f"最终有效样本不足：{len(df)} 只")
            return None, None, len(df), 0, 0
        
        # 计算未来 forward_days 日收益率
        df['future_ret'] = (df['future_close'] - df['current_close']) / df['current_close']
        df['future_ret_f'] = (df['future_close_f'] - df['current_close']) / df['current_close']
        
        # 4. 计算 IC (Spearman 相关)
        cmmr_ic = df['cmmr_score'].corr(df['future_ret'], method='spearman')
        fusion_ic = df['fusion_score_cmmr'].corr(df['future_ret_f'], method='spearman')
        
        # 计算胜率（高于中位数的股票未来上涨的比例）
        cmmr_median = df['cmmr_score'].median()
        cmmr_above = df[df['cmmr_score'] > cmmr_median]
        cmmr_win_rate = (cmmr_above['future_ret'] > 0).mean() if len(cmmr_above) > 0 else 0
        
        fusion_median = df['fusion_score_cmmr'].median()
        fusion_above = df[df['fusion_score_cmmr'] > fusion_median]
        fusion_win_rate = (fusion_above['future_ret'] > 0).mean() if len(fusion_above) > 0 else 0
        
        return cmmr_ic, fusion_ic, len(df), cmmr_win_rate, fusion_win_rate
    
    finally:
        conn.close()

def _ensure_forward_days_col(conn, table):
    """幂等添加 forward_days 列（SQLite 无 ADD COLUMN IF NOT EXISTS）"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if 'forward_days' not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN forward_days INTEGER")
        print(f"  {table} 已添加 forward_days 列")

def save_ic_to_db(date_str, cmmr_ic, fusion_ic, sample_count, cmmr_win_rate, fusion_win_rate,
                  forward_days, forward_days_fusion=None):
    """将 IC 结果存入 signals.db（09-20 分窗：两表 forward_days 各记各的窗口）"""
    fd_f = forward_days if forward_days_fusion is None else forward_days_fusion
    conn = sqlite3.connect(STATE_DB)
    try:
        # 创建表（如果不存在）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cmmr_ic_daily (
                date TEXT PRIMARY KEY,
                ic REAL,
                samples INTEGER,
                positive_days INTEGER,
                win_rate REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fusion_ic_daily (
                date TEXT PRIMARY KEY,
                ic REAL,
                samples INTEGER,
                positive_days INTEGER,
                win_rate REAL
            )
        """)
        _ensure_forward_days_col(conn, 'cmmr_ic_daily')
        _ensure_forward_days_col(conn, 'fusion_ic_daily')
        
        # 插入数据
        if cmmr_ic is not None:
            conn.execute("""
                INSERT OR REPLACE INTO cmmr_ic_daily (date, ic, samples, win_rate, forward_days)
                VALUES (?, ?, ?, ?, ?)
            """, (date_str, cmmr_ic, sample_count, cmmr_win_rate, forward_days))
        
        if fusion_ic is not None:
            conn.execute("""
                INSERT OR REPLACE INTO fusion_ic_daily (date, ic, samples, win_rate, forward_days)
                VALUES (?, ?, ?, ?, ?)
            """, (date_str, fusion_ic, sample_count, fusion_win_rate, fd_f))
        
        conn.commit()
        print(f"\n已保存: {date_str} (前向窗口 cmmr={forward_days}日 / fusion={fd_f}日)")
        if cmmr_ic is not None:
            print(f"  CMMR IC: {cmmr_ic:.4f} (胜率{cmmr_win_rate:.1%}, 样本{sample_count})")
        if fusion_ic is not None:
            print(f"  Fusion IC: {fusion_ic:.4f} (胜率{fusion_win_rate:.1%}, 样本{sample_count})")
    
    finally:
        conn.close()

def _ensure_tables(conn):
    """建表 + forward_days 列（幂等），main 与单日模式共用"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cmmr_ic_daily (
            date TEXT PRIMARY KEY,
            ic REAL,
            samples INTEGER,
            positive_days INTEGER,
            win_rate REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fusion_ic_daily (
            date TEXT PRIMARY KEY,
            ic REAL,
            samples INTEGER,
            positive_days INTEGER,
            win_rate REAL
        )
    """)
    _ensure_forward_days_col(conn, 'cmmr_ic_daily')
    _ensure_forward_days_col(conn, 'fusion_ic_daily')


def run_backfill():
    """回填模式（2026-09-20 分窗改造）。

    两表独立定稿：
    - cmmr_ic_daily：未来交易日 >= 10 → 定稿 forward_days=10（对齐 cmmr 账户 rebalance=10）；
      不足 10 → partial=min(avail,10)。
    - fusion_ic_daily：>= 20 → 定稿 20（对齐 cmmr_fusion 账户信号窗 20d）；不足 → partial=min(avail,20)。
    - 跳过判断改为**精确相等**（has_fd == want_fd 才跳过）。旧判断 has_fd >= want_fd 在
      窗口从 20 降到 10 时会把历史 20d 行当已定稿、永不重算——09-20 实锤坑。
    面板滚动统计各取自己定稿窗的行。"""
    conn = sqlite3.connect(STATE_DB)
    tconn = duckdb.connect(str(TUSHARE_DB), read_only=True)
    _ensure_tables(conn)

    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
    done = partial = skipped = 0
    for d in dates:
        avail = tconn.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?", (d,)
        ).fetchone()[0]
        if avail == 0:
            skipped += 1
            continue
        want_c = min(10, avail)   # cmmr 定稿窗 10
        want_f = min(20, avail)   # fusion 定稿窗 20
        date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        have_c = conn.execute(
            "SELECT forward_days FROM cmmr_ic_daily WHERE date = ?", (date_str,)).fetchone()
        have_f = conn.execute(
            "SELECT forward_days FROM fusion_ic_daily WHERE date = ?", (date_str,)).fetchone()
        ok_c = have_c is not None and (have_c[0] or 0) == want_c
        ok_f = have_f is not None and (have_f[0] or 0) == want_f
        if ok_c and ok_f:
            skipped += 1
            continue
        result = calculate_cmmr_fusion_ic(date_str, forward_days=want_c, forward_days_fusion=want_f)
        if result[0] is not None:
            cmmr_ic, fusion_ic, n, cwr, fwr = result
            if not ok_c:
                save_ic_to_db(date_str, cmmr_ic, None, n, cwr, 0, want_c)
            if not ok_f:
                save_ic_to_db(date_str, None, fusion_ic, n, 0, fwr, want_c, want_f)
            if avail >= 10:
                done += 1
            else:
                partial += 1
        else:
            print(f"  {date_str}: 样本不足或数据缺失，跳过")
            skipped += 1
    conn.close()
    tconn.close()
    print(f"\n回填完成：定稿(cmmr=10d窗) {done} 天，partial {partial} 天，跳过 {skipped} 天")


def run_top10_backfill():
    """组合口径轨（2026-09-20 新增）：cmmr 账户真实选池的 top10 未来10日等权收益。

    全截面 Spearman 量不出 80+ 池内排序能力（90% 并列 0 分稀释），账户好坏实际
    由"池内 top10 vs 池均 / vs 全市场中位"的超额决定（配对检验口径的展示版）。
    选池/键序与 strategy_accounts_daily cmmr 分支完全一致：
    cmmr_score>=80 池，ORDER BY cmmr DESC, COALESCE(fusion_score,0) DESC, stock_code。
    落表 cmmr_top10_ic_daily(date, top10_ret, pool_mean, mkt_median, excess_pool,
    excess_mkt, n_pool, forward_days)，定稿窗=10（与 cmmr 账户重评窗对齐）。"""
    conn = sqlite3.connect(STATE_DB)
    tconn = duckdb.connect(str(TUSHARE_DB), read_only=True)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cmmr_top10_ic_daily (
            date TEXT PRIMARY KEY,
            top10_ret REAL, pool_mean REAL, mkt_median REAL,
            excess_pool REAL, excess_mkt REAL, n_pool INTEGER, forward_days INTEGER)
    """)
    conn.commit()
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1").fetchall()]
    done = skip = 0
    for d in dates:
        avail = tconn.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?", (d,)
        ).fetchone()[0]
        want = min(10, avail)
        date_str = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        ex = conn.execute(
            "SELECT forward_days FROM cmmr_top10_ic_daily WHERE date=?", (date_str,)).fetchone()
        if avail == 0 or (ex is not None and (ex[0] or 0) == want):
            skip += 1
            continue
        df = pd.read_sql_query(
            "SELECT stock_code, cmmr_score, COALESCE(fusion_score,0) AS fs "
            "FROM signal_history WHERE REPLACE(date,'-','')=?", conn, params=(d,))
        if len(df) < 500:
            skip += 1
            continue
        df['ts_code'] = df['stock_code'].apply(
            lambda c: f"{c}.SH" if c.startswith(('6', '68', '9')) else f"{c}.SZ")
        cur = get_batch_prices(df['stock_code'].tolist(), date_str, forward_days=0)
        fut = get_batch_prices(df['stock_code'].tolist(), date_str, forward_days=want)
        df['r'] = [((fut.get(t) - cur[t]) / cur[t] * 100
                    if t in fut and t in cur and cur.get(t) else None)
                   for t in df['ts_code']]
        df = df.dropna(subset=['r'])
        pool = df[df['cmmr_score'] >= 80].sort_values(
            ['cmmr_score', 'fs', 'stock_code'], ascending=[False, False, True])
        if len(pool) < 10:
            skip += 1
            continue
        top10 = float(pool['r'].head(10).mean())
        pm = float(pool['r'].mean())
        mm = float(df['r'].median())
        conn.execute(
            "INSERT OR REPLACE INTO cmmr_top10_ic_daily VALUES (?,?,?,?,?,?,?,?)",
            (date_str, round(top10, 4), round(pm, 4), round(mm, 4),
             round(top10 - pm, 4), round(top10 - mm, 4), len(pool), want))
        conn.commit()
        done += 1
    conn.close(); tconn.close()
    print(f"top10 组合轨回填：{done} 天，跳过 {skip} 天")


def main():
    if len(sys.argv) > 1:
        # 单日手工模式：python3 cmmr_ic_daily.py 2026-09-11 [forward_days]
        date_str = sys.argv[1]
        tconn = duckdb.connect(str(TUSHARE_DB), read_only=True)
        avail = tconn.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ?",
            (date_str.replace('-', ''),)
        ).fetchone()[0]
        tconn.close()
        if avail == 0:
            print(f"{date_str} 之后无未来交易日数据，跳过（等数据更新后再算）")
            return
        forward_days = min(10, max(1, avail))          # cmmr 定稿窗 10（09-20）
        forward_days_fusion = min(20, max(1, avail))   # fusion 定稿窗 20
        if len(sys.argv) > 2:
            forward_days = min(int(sys.argv[2]), avail)
            forward_days_fusion = forward_days
        print(f"可用后续交易日: {avail} 天, 前向窗口: cmmr={forward_days} fusion={forward_days_fusion}")
        print(f"计算 {date_str} 的 CMMR IC...")
        result = calculate_cmmr_fusion_ic(date_str, forward_days=forward_days,
                                          forward_days_fusion=forward_days_fusion)
        if result[0] is not None:
            cmmr_ic, fusion_ic, sample_count, cmmr_win_rate, fusion_win_rate = result
            save_ic_to_db(date_str, cmmr_ic, fusion_ic, sample_count, cmmr_win_rate,
                          fusion_win_rate, forward_days, forward_days_fusion)
        else:
            print("无法计算 IC（样本不足或数据缺失）")
    else:
        run_backfill()
        run_top10_backfill()

if __name__ == '__main__':
    main()
