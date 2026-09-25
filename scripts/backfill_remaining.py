#!/usr/bin/env python3
"""快速补完剩余历史数据 - 单线程+25s超时"""
import duckdb, os, sys, time, json, threading
from datetime import date, timedelta
import pandas as pd
import akshare as ak

DB_PATH = os.path.expanduser("~/.hermes/stockdb/stock.db")
TARGET_START = date(2024, 1, 1)
STATE_FILE = os.path.expanduser("~/.hermes/stockdb/backfill_hist_state.json")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"done2": [], "failed2": []}

def save_state(s):
    with open(STATE_FILE, 'w') as f:
        json.dump(s, f)

def fetch_one(code, first_date):
    """超时安全拉取"""
    start_str = TARGET_START.strftime('%Y%m%d')
    end_str = (first_date - timedelta(days=1)).strftime('%Y%m%d')

    result = [None, None]

    def worker():
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start_str, end_date=end_str, adjust="qfq"
            )
            result[0] = df
        except Exception as e:
            result[1] = str(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=25)
    if t.is_alive():
        return code, 0, "TIMEOUT"
    if result[1]:
        return code, 0, result[1]
    df = result[0]
    if df is None or df.empty:
        return code, 0, None

    rename = {
        '日期': 'date', '开盘': 'open', '收盘': 'close',
        '最高': 'high', '最低': 'low',
        '成交量': 'volume', '成交额': 'amount',
        '振幅': 'amplitude', '涨跌幅': 'change_pct', '换手率': 'turn_rate'
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df['stock_code'] = code
    df['date'] = pd.to_datetime(df['date']).dt.date

    local_db = duckdb.connect(DB_PATH)
    try:
        inserted = 0
        local_db.execute("BEGIN TRANSACTION")
        for _, row in df.iterrows():
            rd = row['date']
            if rd < first_date:
                vals = [code, str(rd)]
                for k in ['open','close','high','low','volume','amount','amplitude','change_pct','turn_rate']:
                    v = row.get(k)
                    vals.append(float(v) if pd.notna(v) else None)
                local_db.execute(
                    """INSERT OR REPLACE INTO stock_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)""", vals)
                inserted += 1
        local_db.execute("COMMIT")
        return code, inserted, None
    finally:
        local_db.close()

def main():
    sys.stdout.reconfigure(line_buffering=True)
    state = load_state()
    done_set = set(state.get("done2", []))
    failed_set = set(state.get("failed2", []))

    conn = duckdb.connect(DB_PATH, read_only=True)
    rows = conn.execute("""
        SELECT stock_code, MIN(date), COUNT(*)
        FROM stock_daily
        GROUP BY stock_code
        HAVING COUNT(*) < 200 AND MIN(date) > DATE '2024-01-01'
        ORDER BY stock_code
    """).fetchall()
    conn.close()

    todo = [(c, f, d) for c, f, d in rows if c not in done_set and c not in failed_set]
    print(f"剩余: {len(todo)} 只 (已完成{len(done_set)}, 失败{len(failed_set)})")

    total_inserted = 0
    start = time.time()
    for i, (code, first, days) in enumerate(todo, 1):
        c, inserted, err = fetch_one(code, first)
        if err:
            failed_set.add(code)
            print(f"  {i}/{len(todo)} ❌ {code}: {err[:40]}", flush=True)
        else:
            done_set.add(code)
            total_inserted += inserted
            if inserted > 0:
                print(f"  {i}/{len(todo)} ✅ {code}: +{inserted}行", flush=True)

        if i % 100 == 0 or i == len(todo):
            elapsed = time.time() - start
            rate = i / elapsed * 60 if elapsed > 0 else 0
            eta = (len(todo) - i) / rate * 60 if rate > 0 else 0
            print(f"  进度: {i}/{len(todo)} (+{total_inserted}行) {rate:.0f}只/分 ETA:{eta:.0f}分", flush=True)
            state['done2'] = list(done_set)
            state['failed2'] = list(failed_set)
            save_state(state)
        time.sleep(0.8)

    state['done2'] = list(done_set)
    state['failed2'] = list(failed_set)
    save_state(state)

    elapsed = time.time() - start
    print(f"\n✅ 完成! 耗时{elapsed/60:.1f}分, 成功{len(done_set)}, 失败{len(failed_set)}, 新增{total_inserted}行")

    conn2 = duckdb.connect(DB_PATH, read_only=True)
    s200 = conn2.execute("SELECT COUNT(*) FROM (SELECT 1 FROM stock_daily GROUP BY stock_code HAVING COUNT(*)>=200)").fetchone()[0]
    tot = conn2.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    print(f"≥200天: {s200}/5522 总行数: {tot:,}")
    conn2.close()

if __name__ == '__main__':
    main()
