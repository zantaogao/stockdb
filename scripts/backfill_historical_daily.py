#!/usr/bin/env python3
"""
历史日K线回补脚本 — 补全2024年起的日线数据，确保MA200可用
只补缺失的早期数据，不重复拉取已有数据
用法: python3 backfill_historical_daily.py [--workers 2]
"""
import os, sys, time, json, argparse
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import pandas as pd
import akshare as ak

DB_PATH = os.path.expanduser("~/.hermes/stockdb/stock.db")

# 想要数据到多早：2024-01-01 足够覆盖200个交易日
TARGET_START = date(2024, 1, 1)
STATE_FILE = os.path.expanduser("~/.hermes/stockdb/backfill_hist_state.json")


def get_db():
    return duckdb.connect(DB_PATH)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"done": [], "failed": []}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False)


def get_stocks_needing_backfill(conn):
    """获取需要补数据的股票：最早日期 > TARGET_START"""
    rows = conn.execute("""
        SELECT stock_code, MIN(date) as first_date, MAX(date) as last_date, COUNT(*) as days
        FROM stock_daily
        GROUP BY stock_code
        ORDER BY first_date
    """).fetchall()

    needs_backfill = []
    for code, first, last, cnt in rows:
        if first is None:
            continue
        if cnt < 200 and first > TARGET_START:
            needs_backfill.append((code, first, last, cnt))
    return needs_backfill


def backfill_one(code, first_date):
    """拉取单只股票历史数据"""
    try:
        start_str = TARGET_START.strftime('%Y%m%d')
        end_str = (first_date - timedelta(days=1)).strftime('%Y%m%d')

        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start_str, end_date=end_str, adjust="qfq"
        )
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

        # 只写入目标 start ~ first_date-1 的缺失数据
        local_db = duckdb.connect(DB_PATH)
        try:
            inserted = 0
            local_db.execute("BEGIN TRANSACTION")
            for _, row in df.iterrows():
                rd = row['date']
                if rd < first_date:
                    local_db.execute(
                        """INSERT OR REPLACE INTO stock_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [
                            code, str(rd),
                            float(row.get('open', 0)) if pd.notna(row.get('open')) else None,
                            float(row.get('close', 0)) if pd.notna(row.get('close')) else None,
                            float(row.get('high', 0)) if pd.notna(row.get('high')) else None,
                            float(row.get('low', 0)) if pd.notna(row.get('low')) else None,
                            int(row.get('volume', 0)) if pd.notna(row.get('volume')) else None,
                            float(row.get('amount', 0)) if pd.notna(row.get('amount')) else None,
                            float(row.get('amplitude', 0)) if pd.notna(row.get('amplitude')) else None,
                            float(row.get('change_pct', 0)) if pd.notna(row.get('change_pct')) else None,
                            float(row.get('turn_rate', 0)) if pd.notna(row.get('turn_rate')) else None,
                        ]
                    )
                    inserted += 1
            local_db.execute("COMMIT")
            return code, inserted, None
        finally:
            local_db.close()
    except Exception as e:
        return code, 0, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=1,
                        help='并行线程数（默认1，防封IP）')
    parser.add_argument('--resume', action='store_true',
                        help='从上次中断处继续')
    parser.add_argument('--batch-size', type=int, default=200,
                        help='每批进度保存间隔')
    args = parser.parse_args()

    today = date.today()
    print(f"\n📥 历史日K线回补 — {today}")
    print(f"  目标起点: {TARGET_START} (确保200交易日)")
    print(f"  线程数: {args.workers}")

    # 加载状态
    state = load_state() if args.resume else {"done": [], "failed": []}
    done_set = set(state.get("done", []))
    failed_set = set(state.get("failed", []))

    # 获取需要补数据的股票
    conn = get_db()
    needs = get_stocks_needing_backfill(conn)
    total = len(needs)
    print(f"\n  需要补数据的股票: {total} 只")

    # 已完成的
    todo = [(c, f, l, d) for c, f, l, d in needs
            if c not in done_set and c not in failed_set]
    print(f"  已完成: {len(done_set)}，失败: {len(failed_set)}，待处理: {len(todo)}")

    if not todo:
        print("  ✅ 全部完成，无需补充")
        conn.close()
        return

    # 统计需要补的天数
    total_days_needed = sum((f - TARGET_START).days for _, f, _, _ in todo)
    print(f"  预计补充: ~{total_days_needed} 行数据")

    # 运行
    total_inserted = 0
    completed = 0
    errors = 0
    start_time = time.time()

    if args.workers > 1:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            for code, first, last, cnt in todo:
                fut = pool.submit(backfill_one, code, first)
                futures[fut] = code
            for fut in as_completed(futures):
                code = futures[fut]
                c, inserted, err = fut.result()
                if err:
                    failed_set.add(code)
                    errors += 1
                    print(f"  ❌ {code}: {err[:60]}", flush=True)
                else:
                    done_set.add(code)
                    total_inserted += inserted
                completed += 1
                if completed % args.batch_size == 0:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (len(todo) - completed) / rate if rate > 0 else 0
                    print(f"  进度: {completed}/{len(todo)} ({total_inserted}行) "
                          f"{rate:.1f}只/分 ETA:{eta/60:.0f}分", flush=True)
                    state['done'] = list(done_set)
                    state['failed'] = list(failed_set)
                    save_state(state)
                time.sleep(0.3)
    else:
        # 单线程，更稳定
        for code, first, last, cnt in todo:
            c, inserted, err = backfill_one(code, first)
            if err:
                failed_set.add(code)
                errors += 1
                print(f"  ❌ {code}: {err[:60]}", flush=True)
            else:
                done_set.add(code)
                total_inserted += inserted
            completed += 1
            if completed % 100 == 0 or completed == len(todo):
                elapsed = time.time() - start_time
                rate = completed / elapsed * 60 if elapsed > 0 else 0
                remaining = len(todo) - completed
                eta_min = remaining / rate if rate > 0 else 0
                print(f"  进度: {completed}/{len(todo)} ({total_inserted}行) "
                      f"{rate:.0f}只/分 ETA:{eta_min:.0f}分", flush=True)
                state['done'] = list(done_set)
                state['failed'] = list(failed_set)
                save_state(state)
            time.sleep(0.3)

    # 最终统计
    state['done'] = list(done_set)
    state['failed'] = list(failed_set)
    save_state(state)

    elapsed = time.time() - start_time
    print(f"\n  ✅ 回补完成")
    print(f"  耗时: {elapsed/60:.1f}分")
    print(f"  成功: {len(done_set)} 只，新增 {total_inserted} 行")
    print(f"  失败: {errors} 只")

    # 总数据量
    conn2 = get_db()
    total_records = conn2.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    total_stocks = conn2.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
    stocks_200 = conn2.execute("""
        SELECT COUNT(*) FROM (
            SELECT stock_code FROM stock_daily 
            GROUP BY stock_code HAVING COUNT(*) >= 200
        )
    """).fetchone()[0]
    print(f"  总记录数: {total_records}")
    print(f"  有数据的股票: {total_stocks}")
    print(f"  满足200天的股票: {stocks_200}")
    conn2.close()
    conn.close()


if __name__ == '__main__':
    main()
