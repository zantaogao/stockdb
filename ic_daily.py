#!/usr/bin/env python3
"""
每日因子IC监控 — 适配混合架构版
==================================
读 tushare.db (DuckDB) 计算 Rank IC，写入 signals.db (SQLite, v2温层)。

输出表 (signals.db):
  - factor_ic_daily: 每日IC记录
  - factor_ic_roll: 滚动统计 (20日/60日窗口)

用法:
  python3 ic_daily.py                  # 计算最近1个交易日
  python3 ic_daily.py --days 5         # 计算最近5个交易日
  python3 ic_daily.py --full           # 全量重算 (耗时)
  python3 ic_daily.py --roll-only      # 只更新滚动统计
"""
import argparse
import sqlite3
import sys
from datetime import timedelta, datetime
from pathlib import Path
from scipy import stats as sp_stats

import duckdb
import numpy as np

BASE = Path(__file__).parent.resolve()
TUSHARE_DB = str(BASE / 'tushare.db')
STATE_DB = str(BASE / 'signals.db')  # v2温层(原state.db已冻结为pre_split)

HORIZONS = [1, 5, 10]
ROLL_WINDOWS = [20, 60]

BASE_FACTORS = {
    'mom_5':   {'group': 'momentum',   'source': 'daily'},
    'mom_10':  {'group': 'momentum',   'source': 'daily'},
    'mom_20':  {'group': 'momentum',   'source': 'daily'},
    'mom_60':  {'group': 'momentum',   'source': 'daily'},
    'vol_20':  {'group': 'volatility', 'source': 'daily'},
    'vol_60':  {'group': 'volatility', 'source': 'daily'},
    'turn_5':  {'group': 'liquidity',  'source': 'daily'},
    'turn_20': {'group': 'liquidity',  'source': 'daily'},
    'ep_ttm':  {'group': 'valuation',  'source': 'stock_valuation'},
    'bp':      {'group': 'valuation',  'source': 'stock_valuation'},
    'ln_cap':  {'group': 'size',       'source': 'stock_valuation'},
    'roe':     {'group': 'quality',    'source': 'stock_valuation'},
}


# ── 读取：从 tushare.db (DuckDB) ─────────────────────

def _fmt_date(dt):
    """把 datetime 转成 'YYYYMMDD'（tushare.db 格式）"""
    return dt.strftime('%Y%m%d')

def _fmt_date_sql(dt):
    """把 datetime 转成 YYYY-MM-DD（SQL 标准格式）"""
    return dt.strftime('%Y-%m-%d')

def _parse_ymd(s):
    """把 '20260722' 转成 datetime"""
    return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))

def _sub_days(ymd_str, days):
    """从 YYYYMMDD 格式减去 N 天"""
    return _fmt_date(_parse_ymd(ymd_str) - timedelta(days=days))

def _add_days(ymd_str, days):
    """从 YYYYMMDD 格式加上 N 天"""
    return _fmt_date(_parse_ymd(ymd_str) + timedelta(days=days))

def _read_daily(conn, min_date=None, max_date=None):
    """读取日K + 换手率，返回 [(ts_code, date_str, close, turnover_rate, pct_chg)]"""
    where = ''
    params = []
    if min_date and max_date:
        where = 'WHERE d.trade_date >= ? AND d.trade_date <= ?'
        params = [min_date, max_date]
    rows = conn.execute(f"""
        SELECT d.ts_code, d.trade_date, d.close, b.turnover_rate, d.pct_chg
        FROM daily d
        LEFT JOIN daily_basic b ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
        {where}
        ORDER BY d.ts_code, d.trade_date
    """, params).fetchall()
    return rows


def _read_valuation(conn):
    """读取估值数据"""
    return conn.execute("""
        SELECT stock_code, date, pe, pb, total_mv
        FROM stock_valuation
        ORDER BY stock_code, date
    """).fetchall()


def _read_roe(conn):
    """读取 ROE"""
    return conn.execute("""
        SELECT ts_code, end_date, roe
        FROM fin_income
        WHERE roe IS NOT NULL AND roe != ''
        ORDER BY ts_code, end_date
    """).fetchall()


def _read_fwd_close(conn, min_date, max_date):
    """读取收盘价（用于前向收益计算）"""
    return conn.execute("""
        SELECT d.ts_code, d.trade_date, d.close
        FROM daily d
        WHERE d.trade_date >= ? AND d.trade_date <= ?
        ORDER BY d.ts_code, d.trade_date
    """, [min_date, max_date]).fetchall()


# ── 因子计算 ─────────────────────────────────────────

def compute_daily_factors(conn, target_dates=None):
    """从 daily 计算基础因子 (momentum/vol/turn)"""
    if target_dates:
        max_dt = max(target_dates)
        min_s = _sub_days(max_dt, 180)
        max_s = _fmt_date(_parse_ymd(max_dt))
        print(f'  读取 daily ({min_s}~{max_s})...')
        rows = _read_daily(conn, min_s, max_s)
    else:
        print('  读取 daily...')
        rows = _read_daily(conn)

    by_stock = {}
    for code, dt, close, turn, chg in rows:
        ds = str(dt).replace('-', '')
        by_stock.setdefault(code, []).append((ds, close, turn, chg))

    factors = {name: {} for name in BASE_FACTORS if BASE_FACTORS[name]['source'] == 'daily'}

    for code, data in by_stock.items():
        data.sort(key=lambda x: x[0])
        closes = [d[1] for d in data]
        turns = [d[2] for d in data]
        dates = [d[0] for d in data]
        changes = [d[3] for d in data]
        n = len(closes)

        for i in range(n):
            dt_str, c = dates[i], closes[i]
            # momentum
            for lag in [5, 10, 20, 60]:
                if i >= lag and closes[i - lag] > 0:
                    fkey = f'mom_{lag}'
                    factors[fkey].setdefault(dt_str, {})[code] = c / closes[i - lag] - 1
            # turn
            for window in [5, 20]:
                if i >= window - 1 and turns[i] is not None:
                    fkey = f'turn_{window}'
                    vals = [turns[j] for j in range(i - window + 1, i + 1) if turns[j] is not None]
                    if vals:
                        factors[fkey].setdefault(dt_str, {})[code] = float(np.mean(vals))
            # volatility
            for window in [20, 60]:
                if i >= window:
                    fkey = f'vol_{window}'
                    vals = [changes[j] for j in range(i - window, i + 1) if changes[j] is not None]
                    if len(vals) >= window:
                        factors[fkey].setdefault(dt_str, {})[code] = float(np.std(vals, ddof=1) * np.sqrt(252))

    return factors


def compute_valuation_factors(conn):
    """从 stock_valuation / fin_income 计算估值因子"""
    print('  读取 stock_valuation...')
    factors = {'ep_ttm': {}, 'bp': {}, 'ln_cap': {}, 'roe': {}}
    for code, dt, pe, pb, mv in _read_valuation(conn):
        dt_str = str(dt).replace('-', '')
        if pe and float(pe) > 0:
            factors['ep_ttm'].setdefault(dt_str, {})[code] = 1.0 / float(pe)
        if pb and float(pb) > 0:
            factors['bp'].setdefault(dt_str, {})[code] = 1.0 / float(pb)
        if mv and float(mv) > 0:
            factors['ln_cap'].setdefault(dt_str, {})[code] = float(np.log(float(mv)))

    print('  读取 fin_income (ROE)...')
    for code, end_dt, roe_val in _read_roe(conn):
        dt_str = str(end_dt).replace('-', '')
        try:
            factors['roe'].setdefault(dt_str, {})[code] = float(roe_val)
        except (ValueError, TypeError):
            pass
    return factors


def get_forward_returns(conn, target_dates):
    """计算前向收益率，返回 {date_str: {code: {horizon: ret}}}"""
    max_dt = max(target_dates)
    min_dt = _sub_days(max_dt, 756)
    max_str = _add_days(max_dt, 10)
    print(f'  读取 daily ({min_dt}~{max_str})...')
    rows = _read_fwd_close(conn, min_dt, max_str)

    by_stock = {}
    for code, dt, close in rows:
        ds = str(dt).replace('-', '')
        by_stock.setdefault(code, []).append((ds, close))

    fwd = {}
    for code, data in by_stock.items():
        data.sort(key=lambda x: x[0])
        dates = [d[0] for d in data]
        closes = [d[1] for d in data]
        n = len(closes)
        for i in range(n):
            dt_str, c0 = dates[i], closes[i]
            if c0 <= 0:
                continue
            for h in HORIZONS:
                if i + h < n and closes[i + h] > 0:
                    ret = closes[i + h] / c0 - 1
                    fwd.setdefault(dt_str, {}).setdefault(code, {})[h] = ret
    return fwd


def compute_rank_ic(factor_values, returns):
    """计算 Rank IC (Spearman)"""
    common = set(factor_values.keys()) & set(returns.keys())
    if len(common) < 30:
        return None, None, len(common)
    fv = [factor_values[c] for c in common]
    rv = [returns[c] for c in common]
    mask = np.isfinite(fv) & np.isfinite(rv)
    fv_clean = [fv[i] for i in range(len(fv)) if mask[i]]
    rv_clean = [rv[i] for i in range(len(rv)) if mask[i]]
    if len(fv_clean) < 30:
        return None, None, len(fv_clean)
    rho, pval = sp_stats.spearmanr(fv_clean, rv_clean)
    return rho, pval, len(fv_clean)


# ── 写入：signals.db (SQLite 温层) ────────────────────────────

def ensure_tables(sdb):
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS factor_ic_daily (
            date TEXT NOT NULL,
            factor_name TEXT NOT NULL,
            rank_ic REAL,
            p_value REAL,
            n_stocks INTEGER,
            ret_horizon INTEGER NOT NULL,
            PRIMARY KEY (date, factor_name, ret_horizon)
        )
    """)
    sdb.execute("""
        CREATE TABLE IF NOT EXISTS factor_ic_roll (
            factor_name TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            window INTEGER NOT NULL,
            mean_ic REAL,
            std_ic REAL,
            icir REAL,
            win_rate REAL,
            max_ic REAL,
            min_ic REAL,
            n_days INTEGER,
            ret_horizon INTEGER NOT NULL,
            group_name TEXT,
            PRIMARY KEY (factor_name, as_of_date, window, ret_horizon)
        )
    """)
    print('  表结构已就绪 (signals.db)')


def write_ic_daily(sdb, records):
    if not records:
        print('  无IC记录可写入')
        return
    dates = list(set(r[0] for r in records))
    placeholders = ','.join('?' for _ in dates)
    sdb.execute(f'DELETE FROM factor_ic_daily WHERE date IN ({placeholders})', dates)
    sdb.executemany(
        'INSERT OR REPLACE INTO factor_ic_daily (date, factor_name, rank_ic, p_value, n_stocks, ret_horizon) '
        'VALUES (?, ?, ?, ?, ?, ?)', records)
    sdb.commit()
    print(f'  写入 {len(records)} 条IC记录')


def write_roll_stats(sdb, records):
    if not records:
        print('  无滚动统计数据')
        return
    sdb.execute('DELETE FROM factor_ic_roll')
    sdb.executemany(
        'INSERT OR REPLACE INTO factor_ic_roll '
        '(factor_name, as_of_date, window, mean_ic, std_ic, icir, win_rate, max_ic, min_ic, n_days, ret_horizon, group_name) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', records)
    sdb.commit()
    print(f'  写入 {len(records)} 条滚动统计')


# ── 滚动统计计算 ─────────────────────────────────────

def compute_roll_stats(sdb):
    print('\n计算滚动统计...')
    combos = sdb.execute(
        'SELECT DISTINCT factor_name, ret_horizon FROM factor_ic_daily ORDER BY factor_name, ret_horizon'
    ).fetchall()
    if not combos:
        print('  无IC数据，跳过')
        return

    roll_records = []
    for fname, h in combos:
        group = BASE_FACTORS.get(fname, {}).get('group', 'unknown')
        ic_rows = sdb.execute(
            'SELECT date, rank_ic FROM factor_ic_daily WHERE factor_name = ? AND ret_horizon = ? ORDER BY date',
            (fname, h)
        ).fetchall()
        if len(ic_rows) < 10:
            continue
        dates = [r[0] for r in ic_rows]
        ics = [r[1] for r in ic_rows]
        for w in ROLL_WINDOWS:
            for i in range(w - 1, len(ics)):
                window = ics[i - w + 1:i + 1]
                as_of = dates[i]
                mean_ic = float(np.mean(window))
                std_ic = float(np.std(window, ddof=1)) if w > 1 else 0
                icir = mean_ic / std_ic if std_ic > 0 else 0
                win_rate = sum(1 for x in window if x > 0) / len(window)
                roll_records.append((
                    fname, as_of, w,
                    round(mean_ic, 6), round(std_ic, 6), round(icir, 4),
                    round(win_rate, 4),
                    round(float(np.max(window)), 6), round(float(np.min(window)), 6),
                    w, h, group
                ))
    write_roll_stats(sdb, roll_records)


# ── 主函数 ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='每日因子IC监控')
    parser.add_argument('--days', type=int, default=1, help='计算最近N个交易日')
    parser.add_argument('--full', action='store_true', help='全量重算')
    parser.add_argument('--roll-only', action='store_true', help='只计算滚动统计')
    parser.add_argument('--date', type=str, default=None, help='指定日期 YYYYMMDD')
    args = parser.parse_args()

    # 连接 tushare.db 读数据
    src = duckdb.connect(TUSHARE_DB, read_only=True)
    # 连接 signals.db(v2温层) 写结果
    sdb = sqlite3.connect(STATE_DB)
    sdb.execute('PRAGMA journal_mode=WAL')
    sdb.execute('PRAGMA busy_timeout=30000')
    ensure_tables(sdb)

    if args.roll_only:
        compute_roll_stats(sdb)
        sdb.close()
        src.close()
        return

    # 获取最新行情日期
    last_row = src.execute('SELECT MAX(trade_date) FROM daily').fetchone()
    if not last_row or not last_row[0]:
        print('错误: daily 中没有数据')
        sys.exit(1)
    latest_str = str(last_row[0]).replace('-', '')

    # 确定目标日期
    if args.date:
        target_dates = [args.date]
    elif args.full:
        # trade_date 是 YYYYMMDD 格式字符串, 用字符串比较
        lb = (datetime.now() - timedelta(days=365)).strftime('%Y%m%d')
        rows = src.execute("""
            SELECT DISTINCT trade_date FROM daily
            WHERE trade_date >= ?
            ORDER BY trade_date
        """, [lb]).fetchall()
        target_dates = [str(r[0]).replace('-', '') for r in rows]
    else:
        # 取最近有 mom_5 数据的交易日
        print('  扫描最近 daily 以确定目标日期...')
        lb = _sub_days(latest_str, 180)
        rows = _read_fwd_close(src, lb, last_row[0])
        by_stock = {}
        for code, dt, close in rows:
            ds = str(dt).replace('-', '')
            by_stock.setdefault(code, []).append((ds, close))
        all_dates = set()
        for code, data in by_stock.items():
            data.sort(key=lambda x: x[0])
            for i in range(5, len(data)):
                if data[i][1] > 0 and data[i-5][1] > 0:
                    all_dates.add(data[i][0])
        target_dates = sorted(all_dates, reverse=True)[:args.days]
        # 排除最新交易日（无后续行情，算不出前向收益）
        target_dates = [d for d in target_dates if d < latest_str]

    print(f'\n目标日期: {target_dates}')

    # 计算因子
    print('计算基础因子...')
    daily_factors = compute_daily_factors(src, target_dates=target_dates)
    print('计算估值因子...')
    val_factors = compute_valuation_factors(src)
    factors_all = {**daily_factors, **val_factors}

    # 计算前向收益
    print('计算前向收益...')
    fwd = get_forward_returns(src, target_dates)

    # 计算 IR
    ic_records = []
    for dt_str in target_dates:
        day_returns = fwd.get(dt_str, {})
        if not day_returns:
            print(f'  {dt_str}: 无行情数据，跳过')
            continue
        for fname, fdata in factors_all.items():
            day_factors = fdata.get(dt_str, {})
            if not day_factors:
                continue
            for h in HORIZONS:
                rets = {c: v.get(h) for c, v in day_returns.items() if v.get(h) is not None}
                if len(rets) < 30:
                    continue
                rank_ic, pval, n = compute_rank_ic(day_factors, rets)
                if rank_ic is not None:
                    ic_records.append((
                        dt_str, fname, round(float(rank_ic), 6),
                        round(float(pval), 6) if pval else None, n, h
                    ))
        print(f'  {dt_str}: {sum(1 for r in ic_records if r[0]==dt_str)} 条IC')

    write_ic_daily(sdb, ic_records)
    compute_roll_stats(sdb)

    # 输出摘要
    print('\n' + '=' * 60)
    print('IC计算完成')
    for dt_str in target_dates[-1:]:
        print(f'\n  {dt_str} 各因子 IC (1日收益):')
        rows = sdb.execute(
            'SELECT factor_name, rank_ic, p_value, n_stocks FROM factor_ic_daily '
            'WHERE date = ? AND ret_horizon = 1 ORDER BY ABS(rank_ic) DESC',
            (dt_str,)
        ).fetchall()
        for fname, ric, pval, n in rows[:15]:
            sig = '**' if (pval and pval < 0.01) else '*' if (pval and pval < 0.05) else ' '
            print(f'    {fname:25s} IC={ric:+.4f}  p={pval or 0:.4f}  n={n:>5d} {sig}')

    sdb.close()
    src.close()


if __name__ == '__main__':
    main()
