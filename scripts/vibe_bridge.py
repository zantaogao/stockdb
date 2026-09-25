#!/usr/bin/env python3
"""
Vibe-Trading因子桥接器 — 从DuckDB读取数据，调Vibe-Trading因子库，结果注册到factor_library
"""
import os, sys, time, importlib, json, tempfile
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

HOME = os.path.expanduser('~')
if sys.platform == 'win32' or os.path.exists('C:\\'):
    DB = r"C:\Users\pumma\factor_lib\stock.db"
else:
    DB = os.path.join(HOME, '.hermes/stockdb/stock.db')

# 动态导入Vibe-Trading的因子
FACTOR_ZOO = {
    'gtja191': {'module': 'src.factors.zoo.gtja191', 'count': 191, 'label': '国泰君安'},
    'alpha101': {'module': 'src.factors.zoo.alpha101', 'count': 101, 'label': 'Kakushadze'},
    'qlib158': {'module': 'src.factors.zoo.qlib158', 'count': 158, 'label': 'Microsoft Qlib'},
}

def build_panel(con, start_date='2024-01-01', end_date=None):
    """从DuckDB构建Vibe-Trading所需的panel格式（wide DataFrame）"""
    if end_date is None:
        end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
    
    # 拉取日线数据
    df = con.execute(f"""
        SELECT stock_code, date, open, close, high, low, volume, amount, change_pct/100.0 as returns
        FROM stock_daily
        WHERE date >= '{start_date}' AND date <= '{end_date}'
        ORDER BY date, stock_code
    """).fetchdf()
    
    if len(df) == 0:
        return None
    
    # 转为 wide format (index=date, columns=stock_code)
    panel = {}
    for col in ['open', 'close', 'high', 'low', 'volume', 'amount', 'returns']:
        panel[col] = df.pivot_table(index='date', columns='stock_code', values=col)
    
    # VWAP = amount / volume
    panel['vwap'] = panel['amount'] / panel['volume'].replace(0, np.nan)
    
    return panel


def get_available_factors(zoo_name='gtja191'):
    """获取某个zoo里所有可用的因子列表"""
    meta = FACTOR_ZOO[zoo_name]
    factors = []
    for i in range(1, meta['count'] + 1):
        alpha_id = f"alpha_{i:03d}"
        try:
            mod = importlib.import_module(f"{meta['module']}.{alpha_id}")
            factors.append({
                'id': f"{zoo_name}_{alpha_id}",
                'alpha_id': alpha_id,
                'zoo': zoo_name,
                'meta': mod.__alpha_meta__,
                'compute': mod.compute,
            })
        except (ImportError, AttributeError):
            continue
    return factors


def compute_factor(compute_fn, panel, factor_name):
    """调用Vibe-Trading的compute函数，返回series"""
    try:
        result = compute_fn(panel)
        if result is None or len(result) == 0:
            return None
        # 转成long format (date, stock_code, value)
        result = result.stack().reset_index()
        result.columns = ['date', 'stock_code', factor_name]
        result['date'] = result['date'].astype(str)
        return result
    except Exception as e:
        return None


def import_factors(zoo_name='gtja191', max_factors=None, start_date='2024-01-01'):
    """批量导入因子到factor_daily_values"""
    meta = FACTOR_ZOO[zoo_name]
    print(f"导入 {meta['label']} ({meta['count']}个因子)...")
    
    con = duckdb.connect(DB)
    
    # 构建panel
    print("  构建panel...", flush=True)
    panel = build_panel(con, start_date)
    if panel is None:
        print("  无数据")
        con.close()
        return
    print(f"  panel: {panel['close'].shape[0]}天 × {panel['close'].shape[1]}只股票", flush=True)
    
    # 获取因子
    factors = get_available_factors(zoo_name)
    if max_factors:
        factors = factors[:max_factors]
    print(f"  找到{len(factors)}个因子", flush=True)
    
    # 逐因子计算+写入（批量CSV→COPY）
    imported = 0; csv_lines = []; total_lines = 0
    t0 = time.time()
    csv_path = os.path.join(tempfile.gettempdir(), f'vibe_{zoo_name}.csv')
    
    # 先清空因子表里该zoo的旧数据
    con.execute(f"DELETE FROM factor_daily_values WHERE factor_name LIKE '{zoo_name}%'")
    
    for f in factors:
        t1 = time.time()
        result = compute_factor(f['compute'], panel, f['id'])
        if result is None or len(result) == 0:
            continue
        
        for _, row in result.iterrows():
            val = row[f['id']]
            if pd.isna(val) or val is None:
                continue
            csv_lines.append(f"{row['date']}|{row['stock_code']}|{f['id']}|{val}\n")
            total_lines += 1
        
        imported += 1
        if imported % 10 == 0:
            # 写入CSV
            with open(csv_path, 'a') as fh:
                fh.writelines(csv_lines)
            csv_lines = []
            print(f"  [{imported}/{len(factors)}] ({time.time()-t1:.1f}s/因子)", flush=True)
    
    # 写入剩余
    if csv_lines:
        with open(csv_path, 'a') as fh:
            fh.writelines(csv_lines)
    
    # COPY导入
    t_copy = time.time()
    con.execute(f"""
        COPY factor_daily_values (date, stock_code, factor_name, raw_value)
        FROM '{csv_path}' (DELIMITER '|', AUTO_DETECT FALSE)
    """)
    print(f"  COPY导入: {time.time()-t_copy:.0f}s", flush=True)
    
    print(f"\n导入完成: {imported}/{len(factors)}个因子, {total_lines:,}条, {time.time()-t0:.0f}s", flush=True)
    con.close()


def bench_imported(zoo_name='gtja191'):
    """对已导入的因子跑bench"""
    # 从factor_registry获取因子列表
    con = duckdb.connect(DB)
    factors = con.execute(f"""
        SELECT DISTINCT factor_name FROM factor_daily_values 
        WHERE factor_name LIKE '{zoo_name}%'
        ORDER BY factor_name
    """).fetchdf()['factor_name'].tolist()
    con.close()
    
    print(f"\n对{len(factors)}个已导入的{zoo_name}因子跑bench...")
    
    # 调用factor_bench.py
    os.system(f"python3 {os.path.join(os.path.dirname(__file__), 'factor_bench.py')} bench --factors {','.join(factors)}")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'import'
    
    if cmd == 'import':
        zoo = sys.argv[2] if len(sys.argv) > 2 else 'gtja191'
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
        import_factors(zoo, max_factors=limit)
    elif cmd == 'bench':
        zoo = sys.argv[2] if len(sys.argv) > 2 else 'gtja191'
        bench_imported(zoo)
    elif cmd == 'list':
        zoo = sys.argv[2] if len(sys.argv) > 2 else 'gtja191'
        factors = get_available_factors(zoo)
        for f in factors[:20]:
            print(f"{f['id']:25s} {f['meta'].get('formula_latex', '')[:60]}")
        print(f"... 共{len(factors)}个因子")
