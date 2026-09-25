#!/usr/bin/env python3
"""
MacBook 端 GTJA 因子更新
从 stock.db 读取日K数据，用 src/factors/zoo/gtja191 模块计算 GTJA 因子，
输出 gtja_signals.pkl.gz 供评分系统使用。

支持 14 个 GTJA 因子：
  核心 4 个: 006, 083, 177, 184
  扩展 10 个: 001-005, 007-011
"""
import sys, time, importlib, gzip, pickle
import numpy as np, pandas as pd
from pathlib import Path
import duckdb

BASE = Path(__file__).parent.parent
DB = BASE / 'stock.db'
GTJA_PKL = BASE / 'gtja_signals.pkl.gz'

# 14 个 GTJA 因子：(显示名, alpha编号, 反转)
GTJA_MODULES = [
    ('gtja_006', 6, False),
    ('gtja_083', 83, False),
    ('gtja_177', 177, False),
    ('gtja_184', 184, False),
    # 新增 10 个
    ('gtja_001', 1, False),
    ('gtja_002', 2, False),
    ('gtja_003', 3, False),
    ('gtja_004', 4, False),
    ('gtja_005', 5, False),
    ('gtja_007', 7, False),
    ('gtja_008', 8, False),
    ('gtja_009', 9, False),
    ('gtja_010', 10, False),
    ('gtja_011', 11, False),
]

# 添加 src 到 sys.path 使 importlib 能加载因子模块
sys.path.insert(0, str(BASE))


def build_panel(con, lookback_days=300):
    """从 stock.db 构建 panel: {col: DataFrame(date_idx, code_cols)}"""
    df = con.execute(f"""
        WITH latest AS (
            SELECT DISTINCT date FROM stock_daily
            ORDER BY date DESC LIMIT {lookback_days}
        )
        SELECT sd.stock_code, CAST(sd.date AS VARCHAR) as date_str,
               sd.open, sd.close, sd.high, sd.low, sd.volume, sd.amount,
               COALESCE(sd.change_pct, 0) / 100.0 as returns
        FROM stock_daily sd
        JOIN latest l ON sd.date = l.date
        WHERE sd.stock_code NOT LIKE '8%'
          AND sd.stock_code NOT LIKE '4%'
          AND sd.stock_code NOT LIKE '92%'
        ORDER BY date_str, sd.stock_code
    """).fetchdf()

    if len(df) == 0:
        return None

    # 转为 datetime 排序
    df['date'] = pd.to_datetime(df['date_str'])
    df = df.sort_values(['date', 'stock_code'])

    panel = {}
    for col in ['open', 'close', 'high', 'low', 'volume', 'amount', 'returns']:
        panel[col] = df.pivot_table(index='date', columns='stock_code', values=col)

    panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
    return panel


def main():
    t0 = time.time()
    print(f"GTJA 因子更新 (MacBook) | 14 个因子")

    con = duckdb.connect(str(DB), read_only=True)

    # 确定目标日期范围：最新日期往前 300 天（满足最大 warmup 需求）
    latest = con.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    print(f"  最新日期: {latest}")

    panel = build_panel(con, lookback_days=300)
    con.close()

    if panel is None:
        print("  无数据"); return

    print(f"  Panel: {panel['close'].shape[0]} 天 x {panel['close'].shape[1]} 只")

    # 加载已有 pkl（续写用）
    existing = {}
    if GTJA_PKL.exists():
        try:
            with gzip.open(GTJA_PKL, 'rb') as f:
                existing = pickle.load(f)
            print(f"  已有数据: {len(existing)} 个因子")
        except:
            print("  已有数据无法读取，从头开始")

    # 计算每个因子
    results = {}
    fail_count = 0
    for fname, alpha_num, invert in GTJA_MODULES:
        alpha_id = f"alpha_{alpha_num:03d}"
        t1 = time.time()
        try:
            mod = importlib.import_module(f"src.factors.zoo.gtja191.{alpha_id}")
            signal = mod.compute(panel)
        except Exception as e:
            print(f"  {fname} ({alpha_id}): 失败 - {e}")
            fail_count += 1
            continue

        if signal is None or signal.empty:
            print(f"  {fname} ({alpha_id}): 空结果")
            continue

        if invert:
            signal = -signal

        # 合并已有数据（取 union，新数据覆盖旧数据）
        if fname in existing:
            old_df = existing[fname]
            # union 索引和列
            all_idx = sorted(set(old_df.index) | set(signal.index))
            all_cols = sorted(set(old_df.columns) | set(signal.columns))
            merged = old_df.reindex(index=all_idx, columns=all_cols)
            merged.update(signal)  # 新数据覆盖重叠部分
            signal = merged

        results[fname] = signal
        elapsed = time.time() - t1
        non_null = signal.dropna().shape
        print(f"  {fname}: {non_null[0]} 天 x {non_null[1]} 只 ({elapsed:.1f}s)")

    # 保存
    with gzip.open(GTJA_PKL, 'wb') as f:
        pickle.dump(results, f, protocol=pickle.HIGHEST_PROTOCOL)

    total_time = time.time() - t0
    print(f"\n  完成! {len(results)} 个因子, {fail_count} 个失败, {total_time:.0f}s")

    # 验证
    with gzip.open(GTJA_PKL, 'rb') as f:
        verify = pickle.load(f)
    for gn, df in verify.items():
        latest_date = str(df.index[-1])[:10] if len(df.index) > 0 else 'empty'
        print(f"  {gn}: 最新 {latest_date}, shape={df.shape}")


if __name__ == '__main__':
    main()
