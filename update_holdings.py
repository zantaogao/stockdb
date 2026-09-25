#!/usr/bin/env python3
"""更新基金持仓数据 - 补全2024Q2-Q4、2025全年、2026Q1"""
import pandas as pd
import akshare as ak
import duckdb
import json
import time
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

DB_PATH = os.path.expanduser("~/.hermes/stockdb/fund.db")
STATE_PATH = os.path.expanduser("~/.hermes/stockdb/holdings_update_state.json")
MAX_WORKERS = 10
YEARS = ["2024", "2025", "2026"]

# DuckDB connection pool per thread
_db_local = threading.local()

def get_db():
    if not hasattr(_db_local, 'conn'):
        _db_local.conn = db.get_tushare_db()
    return _db_local.conn

def insert_rows(rows):
    """Batch insert holdings data"""
    if not rows:
        return
    conn = get_db()
    conn.executemany(
        "INSERT OR REPLACE INTO fund_holdings (fund_code, report_quarter, stock_code, stock_name, share_count, market_value, hold_pct) VALUES (?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()

def save_state(state):
    state['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_fund_year(code, year):
    """Fetch one fund for one year"""
    try:
        df = ak.fund_portfolio_hold_em(symbol=code, date=year)
        if df is None or df.empty:
            return code, year, [], None
        rows = []
        for _, r in df.iterrows():
            quarter = str(r.get('季度', ''))
            if not quarter:
                continue
            rows.append((
                code,
                quarter,
                str(r.get('股票代码', '')),
                str(r.get('股票名称', '')),
                float(r.get('持股数', 0)) if pd.notna(r.get('持股数')) else None,
                float(r.get('持仓市值', 0)) if pd.notna(r.get('持仓市值')) else None,
                float(r.get('占净值比例', 0)) if pd.notna(r.get('占净值比例')) else None,
            ))
        return code, year, rows, None
    except Exception as e:
        return code, year, [], str(e)[:100]

def main():
    # Clear old data first — we're doing a full refresh
    conn = db.get_tushare_db()
    conn.execute("DELETE FROM fund_holdings")
    conn.commit()
    conn.close()
    print("已清空旧持仓数据", flush=True)
    
    # Load state
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            state = json.load(f)
    else:
        state = {}
    
    done_set = set(tuple(k) for k in state.get('done', []))
    
    # Get fund codes
    conn = db.get_tushare_db()
    fund_codes = [r[0] for r in conn.execute("SELECT fund_code FROM fund_info ORDER BY fund_code").fetchall()]
    conn.close()
    
    total_funds = len(fund_codes)
    total_done = len(done_set)
    total_todo = total_funds * len(YEARS) - total_done
    
    print(f"FUNDS={total_funds} YEARS={YEARS}", flush=True)
    print(f"ALREADY_DONE={total_done} TODO={total_todo}", flush=True)
    
    if total_todo <= 0:
        print("ALL UP TO DATE", flush=True)
        sys.exit(0)
    
    # Build task list: (fund_code, year) pairs not yet done
    tasks = []
    for code in fund_codes:
        for year in YEARS:
            if (code, year) not in done_set:
                tasks.append((code, year))
    
    total = len(tasks)
    done_count = 0
    row_count = 0
    fail_count = 0
    last_save = 0
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_fund_year, code, year): (code, year) for code, year in tasks}
        for i, future in enumerate(as_completed(futures), 1):
            code, year, rows, err = future.result()
            done_count += 1
            done_set.add((code, year))
            
            if err:
                fail_count += 1
                if fail_count <= 5:
                    print(f"  FAIL {code} {year}: {err}", flush=True)
            elif rows:
                insert_rows(rows)
                row_count += len(rows)
            
            # Save state every 500 tasks
            if done_count - last_save >= 500:
                state['done'] = list(done_set)
                state['row_count'] = row_count
                state['fail_count'] = fail_count
                state['progress'] = f"{done_count}/{total}"
                save_state(state)
                last_save = done_count
            
            # Progress every 100
            if done_count % 100 == 0:
                elapsed = time.time() - start_time
                rate = done_count / elapsed if elapsed > 0 else 0
                eta = (total - done_count) / rate if rate > 0 else 0
                print(f"  {done_count}/{total} | rows={row_count} | fail={fail_count} | "
                      f"{rate:.1f}/s | ETA={eta/60:.0f}min", flush=True)
    
    # Final save
    state['done'] = list(done_set)
    state['row_count'] = row_count
    state['fail_count'] = fail_count
    state['progress'] = f"{done_count}/{total}"
    state['completed_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    save_state(state)
    
    elapsed = time.time() - start_time
    print(f"\nDONE: {done_count}/{total} | rows={row_count} | fail={fail_count} | time={elapsed/60:.1f}min", flush=True)

if __name__ == '__main__':
    main()
