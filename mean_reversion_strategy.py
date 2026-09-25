#!/usr/bin/env python3
"""
均值回归策略 — 大盘震荡市专用
================================
不依赖任何现有评分系统，独立运行，独立数据表。

核心逻辑：
1. 检测大盘状态（上证 MA20 斜率）
2. 震荡市才启用选股，趋势市/下跌市跳过
3. 选横盘整理 + 资金吸筹 + 波动收敛的股票

数据源：tushare.db（指数日K + 个股日K）
        signals.db（new_factors, flow_alpha, vol_adj）
写入：signals.db.mean_reversion_signals
"""
import sqlite3
import duckdb
from pathlib import Path
from datetime import datetime

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = str(BASE / 'signals.db')  # v2温层
TUSHARE_DB = str(BASE / 'tushare.db')

MKT_LABEL = {'uptrend': '上升趋势', 'oscillate': '震荡', 'downtrend': '下跌趋势'}


def get_market_state():
    """检测大盘状态"""
    tdx = duckdb.connect(TUSHARE_DB, read_only=True)
    rows = tdx.execute("""
        SELECT trade_date, close FROM index_daily_raw
        WHERE ts_code = '000001.SH'
        ORDER BY trade_date
    """).fetchall()
    tdx.close()
    if len(rows) < 40:
        return ('unknown', 0.0, None)
    closes = [float(r[1]) for r in rows]
    ma20 = sum(closes[-20:]) / 20
    ma20_prev = sum(closes[-40:-20]) / 20
    slope = (ma20 - ma20_prev) / ma20_prev * 100
    state = 'uptrend' if slope > 0.5 else ('oscillate' if slope > -0.3 else 'downtrend')
    return (state, round(slope, 2), str(rows[-1][0])[:10])


def run():
    print("=" * 60)
    print("均值回归策略 — 大盘震荡市专用")
    print("=" * 60)

    state, slope, latest_date = get_market_state()
    print(f"\n大盘状态: {MKT_LABEL.get(state, state)}  (MA20斜率={slope}%)")

    sdb = sqlite3.connect(STATE_DB, timeout=10)
    today_clean = (latest_date or datetime.now().strftime('%Y%m%d')).replace('-', '')

    # 建表+清理旧数据
    sdb.execute("""CREATE TABLE IF NOT EXISTS mean_reversion_signals (
        date TEXT, stock_code TEXT, total_score REAL,
        f1_range REAL, f2_flow REAL, f3_vol REAL, f4_position REAL,
        ma_decay REAL, flow_alpha REAL, vol_adj REAL, close_price REAL,
        PRIMARY KEY (date, stock_code))""")
    sdb.execute(f"DELETE FROM mean_reversion_signals WHERE REPLACE(date,'-','') = '{today_clean}'")
    sdb.execute("INSERT INTO mean_reversion_signals (date, stock_code, total_score) VALUES (?, '__market_state__', ?)",
                (today_clean, {'uptrend': 100, 'oscillate': 50, 'downtrend': 0}.get(state, 50)))

    if state != 'oscillate':
        print(f"\n{'✅' if state == 'uptrend' else '⏭'} 当前{MKT_LABEL.get(state, state)}，跳过选股")
        sdb.commit()
        sdb.close()
        return

    # 震荡市：读取因子数据（从 signals.db）
    # ⚠️ 等值连接（2026-08-04 修复）：三表 date/stock_code 格式一致（YYYY-MM-DD+裸代码），
    # 直接等值连接 0.08s；原 REPLACE 跨表比较无索引，每次 109s（生产 cron 硬扛）
    factors = sdb.execute("""
        SELECT nf.stock_code, nf.ma_decay, fa.flow_alpha, va.vol_adj
        FROM new_factors nf
        LEFT JOIN flow_alpha fa ON nf.stock_code = fa.stock_code AND nf.date = fa.date
        LEFT JOIN vol_adj va ON nf.stock_code = va.stock_code AND nf.date = va.date
        WHERE REPLACE(nf.date,'-','') = ?
    """, [today_clean]).fetchall()
    print(f"  因子数据: {len(factors)} 只")

    if not factors:
        print("  ⚠️ 无因子数据（先跑 new_factors.py）")
        sdb.close()
        return

    # 从 tushare.db 批量读取今日日K
    tdx = duckdb.connect(TUSHARE_DB, read_only=True)
    daily_rows = tdx.execute("""
        SELECT ts_code, close FROM daily
        WHERE trade_date = ?
    """, [today_clean]).fetchall()
    tdx.close()
    # 建立 code→close 映射（去掉后缀）
    close_map = {}
    for ts, cl in daily_rows:
        code = ts.split('.')[0]
        close_map[code] = float(cl) if cl else 0
    print(f"  日K数据: {len(daily_rows)} 只")

    # 计算评分
    results = []
    for row in factors:
        code = row[0]
        ma_decay = float(row[1] or 0)
        flow_a = float(row[2] or 0)
        vol_a = float(row[3] or 0)
        close = close_map.get(code, 0)
        if close <= 0:
            continue

        decay_abs = abs(ma_decay)
        f1 = 30 if decay_abs < 0.5 else (20 if decay_abs < 1.0 else (10 if decay_abs < 3.0 else 0))
        f2 = 30 if flow_a > 0.05 else (20 if flow_a > 0.02 else (10 if flow_a > 0 else 0))
        f3 = 20 if vol_a < 0.05 else (15 if vol_a < 0.1 else (10 if vol_a < 0.2 else (5 if vol_a < 0.5 else 0)))
        f4 = 15 if ma_decay < 0 else (10 if ma_decay < 1.0 else 5)
        total = f1 + f2 + f3 + f4

        results.append({
            'stock_code': code, 'date': today_clean, 'total_score': total,
            'f1_range': f1, 'f2_flow': f2, 'f3_vol': f3, 'f4_position': f4,
            'ma_decay': round(ma_decay, 4), 'flow_alpha': round(flow_a, 4),
            'vol_adj': round(vol_a, 4), 'close_price': round(close, 2),
        })

    if not results:
        print("  ⚠️ 无有效评分")
        sdb.close()
        return

    results.sort(key=lambda x: x['total_score'], reverse=True)

    for r in results[:500]:
        sdb.execute("""INSERT OR REPLACE INTO mean_reversion_signals
            (date,stock_code,total_score,f1_range,f2_flow,f3_vol,f4_position,
             ma_decay,flow_alpha,vol_adj,close_price) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (r['date'], r['stock_code'], r['total_score'],
             r['f1_range'], r['f2_flow'], r['f3_vol'], r['f4_position'],
             r['ma_decay'], r['flow_alpha'], r['vol_adj'], r['close_price']))
    sdb.commit()
    sdb.close()

    # Top 10 输出
    print(f"\n✅ 已写入前 {min(500, len(results))} 只 → mean_reversion_signals")
    print(f"\n{'='*60}")
    print(f"📊 均值回归 Top 10")
    print(f"{'='*60}")
    print(f"{'代码':>10} {'总分':>4} {'横盘':>4} {'资金':>4} {'波动':>4} {'位置':>4} {'现价':>8} {'flow_a':>8}")
    print("-" * 60)
    for r in results[:10]:
        print(f"{r['stock_code']:>10} {r['total_score']:>4} {r['f1_range']:>4} {r['f2_flow']:>4} "
              f"{r['f3_vol']:>4} {r['f4_position']:>4} {r['close_price']:>8.2f} {r['flow_alpha']:>8.4f}")

    bins = [(80, 100), (60, 80), (40, 60), (20, 40), (0, 20)]
    print(f"\n评分分布:")
    for lo, hi in bins:
        n = sum(1 for r in results if lo <= r['total_score'] < hi)
        print(f"  {lo:>3}~{hi:<3}: {n:>4} 只")
    print(f"\n✅ 完成")


if __name__ == '__main__':
    run()
