#!/usr/bin/env python3
"""基金净值增量更新（高效版：并行+断点续传）"""
import os, sys, time, json
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import pandas as pd
import akshare as ak

DB = os.path.expanduser("~/.hermes/stockdb/fund.db")
STATE_PATH = os.path.expanduser("~/.hermes/stockdb/fund_nav_update_state.json")
MAX_WORKERS = 1
DELAY = 0.5
BATCH_SIZE = 100

def get_db():
    return db.get_tushare_db()

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {"processed": 0, "updated": 0, "rows": 0, "failed": 0}

def save_state(state):
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f)

def update_single(code):
    """更新单只基金的净值"""
    local = get_db()
    try:
        today = date.today()
        last = local.execute(
            "SELECT MAX(date) FROM fund_nav_daily WHERE fund_code=?", [code]
        ).fetchone()[0]
        if last and last >= today:
            return code, 0, "up-to-date"
        
        time.sleep(DELAY)  # 减速防封
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        if df is None or df.empty or '净值日期' not in df.columns:
            return code, 0, "no-data"
        
        c = 0
        for _, r in df.iterrows():
            rd = r['净值日期']
            if isinstance(rd, str):
                rd = datetime.strptime(rd, '%Y-%m-%d').date()
            if not last or rd > last:
                local.execute(
                    """INSERT OR REPLACE INTO fund_nav_daily 
                       (fund_code, date, unit_nav, change_pct) 
                       VALUES (?,?,?,?)""",
                    [code, str(rd),
                     float(r.get('单位净值', 0)) if pd.notna(r.get('单位净值')) else None,
                     float(r.get('日增长率', 0)) if pd.notna(r.get('日增长率')) else None]
                )
                c += 1
        if c > 0:
            local.commit()
        return code, c, None
    except Exception as e:
        return code, 0, str(e)[:120]
    finally:
        local.close()

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 基金净值增量更新开始", flush=True)
    
    state = load_state()
    db = get_db()
    
    funds = db.execute(
        "SELECT fund_code FROM fund_info ORDER BY fund_code"
    ).fetchall()
    total = len(funds)
    db.close()
    
    print(f"  共 {total} 只基金", flush=True)
    print(f"  断点续传: 已处理 {state['processed']} 只", flush=True)
    
    remaining = funds[state['processed']:]
    updated = state['updated']
    total_rows = state['rows']
    failed = state['failed']
    processed = state['processed']
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for item in remaining:
            code = item[0]
            fut = pool.submit(update_single, code)
            futures[fut] = code
            if len(futures) >= BATCH_SIZE:
                break
        
        while futures:
            for fut in as_completed(futures):
                code = futures.pop(fut)
                processed += 1
                code, rows, err = fut.result()
                total_rows += rows
                if rows > 0:
                    updated += 1
                if err and err not in ("up-to-date", "no-data"):
                    failed += 1
                
                if processed % 500 == 0:
                    elapsed = time.time() - start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (total - processed) / rate if rate > 0 else 0
                    print(
                        f"  {processed}/{total} | +{total_rows}行 | "
                        f"updated={updated} | fail={failed} | "
                        f"{rate:.1f}条/s | ETA={eta/60:.0f}min",
                        flush=True
                    )
                    save_state({
                        "processed": processed, "updated": updated,
                        "rows": total_rows, "failed": failed
                    })
                
                # Submit next item
                next_idx = processed + len(futures)
                if next_idx < len(remaining):
                    next_code = remaining[next_idx][0]
                    futures[pool.submit(update_single, next_code)] = next_code
                
                if len(futures) == 0:
                    break
    
    elapsed = time.time() - start_time
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 完成", flush=True)
    print(f"  RESULT: {updated}/{total} | rows={total_rows} | fail={failed} | {elapsed/60:.1f}min", flush=True)
    
    # Clear state on success
    os.remove(STATE_PATH)
    
    return 0 if failed < total * 0.5 else 1

if __name__ == '__main__':
    sys.exit(main())
