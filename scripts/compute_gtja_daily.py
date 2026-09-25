#!/usr/bin/env python3
"""
GTJA因子每日增量更新（跑在PC上）
只算最新一天的数据，写入factor_daily_values
"""
import os, sys, time, importlib
import duckdb, numpy as np, pandas as pd

DB = r"C:\Users\pumma\factor_lib\stock.db"

# 39个|IC|>0.02的GTJA因子（含取反版）
GTJA_FACTORS = [
    ('gtja_150_inv', 150, True), ('gtja_158_inv', 158, True), ('gtja_159_inv', 159, True),
    ('gtja_167_inv', 167, True), ('gtja_175_inv', 175, True), ('gtja_187_inv', 187, True),
    ('gtja_184', 184, False), ('gtja_168', 168, False), ('gtja_189_inv', 189, True),
    ('gtja_147_inv', 147, True), ('gtja_151_inv', 151, True), ('gtja_145_inv', 145, True),
    ('gtja_161_inv', 161, True), ('gtja_177', 177, False), ('gtja_157', 157, False),
    ('gtja_144', 144, False), ('gtja_156', 156, False), ('gtja_185', 185, False),
    ('gtja_179_inv', 179, True), ('gtja_140', 140, False), ('gtja_042', 42, False),
    ('gtja_046', 46, False), ('gtja_083', 83, False), ('gtja_099', 99, False),
    ('gtja_041', 41, False), ('gtja_062', 62, False), ('gtja_034', 34, False),
    ('gtja_025', 25, False), ('gtja_016', 16, False), ('gtja_005', 5, False),
    ('gtja_049', 49, False), ('gtja_048', 48, False), ('gtja_032', 32, False),
    ('gtja_026', 26, False), ('gtja_008', 8, False), ('gtja_035', 35, False),
    ('gtja_038', 38, False), ('gtja_001', 1, False), ('gtja_006', 6, False),
]

def build_panel(con):
    """构建250天panel"""
    df = con.execute("""
        WITH latest AS (
            SELECT DISTINCT date FROM stock_daily ORDER BY date DESC LIMIT 250
        )
        SELECT sd.stock_code, sd.date, sd.open, sd.close, sd.high, sd.low, 
               sd.volume, sd.amount, sd.change_pct/100.0 as returns
        FROM stock_daily sd JOIN latest l ON sd.date = l.date
        ORDER BY sd.date, sd.stock_code
    """).fetchdf()
    if len(df) == 0: return None
    panel = {}
    for col in ['open','close','high','low','volume','amount','returns']:
        panel[col] = df.pivot_table(index='date', columns='stock_code', values=col)
    panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
    return panel


def main():
    t0 = time.time()
    con = duckdb.connect(DB)
    
    print(f"GTJA因子每日更新 | {len(GTJA_FACTORS)}个因子", flush=True)
    
    panel = build_panel(con)
    if panel is None:
        print("  ❌ 无日线数据"); con.close(); return
    print(f"  Panel: {panel['close'].shape[0]}天×{panel['close'].shape[1]}只", flush=True)
    
    latest_date = str(panel['close'].index[-1])[:10]
    print(f"  最新日期: {latest_date}", flush=True)
    
    computed = 0
    for fname, alpha_num, invert in GTJA_FACTORS:
        alpha_id = f"alpha_{alpha_num:03d}"
        t1 = time.time()
        try:
            mod = importlib.import_module(f"src.factors.zoo.gtja191.{alpha_id}")
            signal = mod.compute(panel)
        except Exception as e:
            print(f"  ❌ {fname}: {str(e)[:50]}", flush=True); continue
        if signal is None or signal.empty: continue
        
        if invert: signal = -signal
        latest = signal.loc[panel['close'].index[-1]].dropna()
        
        # 批量写入
        con.execute("BEGIN TRANSACTION")
        n = 0
        for code, val in latest.items():
            if pd.isna(val): continue
            con.execute("INSERT OR REPLACE INTO factor_daily_values (date,stock_code,factor_name,raw_value) VALUES (?,?,?,?)",
                       [latest_date, code, fname, float(val)])
            n += 1
        con.execute("COMMIT")
        computed += 1
        print(f"  OK [{computed}/{len(GTJA_FACTORS)}] {fname}: {n}条 ({time.time()-t1:.1f}s)", flush=True)
    
    # Z-score
    print("  Z-score...", flush=True)
    for fname, _, _ in GTJA_FACTORS:
        df = con.execute(f"SELECT stock_code,raw_value FROM factor_daily_values WHERE date='{latest_date}' AND factor_name='{fname}'").fetchdf()
        if len(df) < 10: continue
        vals = np.clip(df['raw_value'].values, *np.percentile(df['raw_value'].values, [1, 99]))
        m, s = np.nanmean(vals), np.nanstd(vals)
        if s > 0:
            for code, z in zip(df['stock_code'], (vals - m) / s):
                con.execute("UPDATE factor_daily_values SET zscore=? WHERE date=? AND stock_code=? AND factor_name=?",
                          [float(z), latest_date, code, fname])
    
    con.close()
    print(f"  ✅ 完成! {computed}/{len(GTJA_FACTORS)}个因子, {time.time()-t0:.0f}s", flush=True)


if __name__ == '__main__':
    main()
