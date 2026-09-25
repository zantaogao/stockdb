#!/usr/bin/env python3
"""
批量补仓历史日线数据（AKShare Sina源版）
使用 ak.stock_zh_a_daily 逐只拉取近半年日线

用法: python3 scripts/backfill_daily.py
支持断点续传: python3 scripts/backfill_daily.py --resume
强制全量重拉: python3 scripts/backfill_daily.py --force
"""
import akshare as ak
import duckdb
import json, sys, time, random
from pathlib import Path
from datetime import datetime, date

DB_DIR = Path.home() / '.hermes' / 'stockdb'
DB_PATH = DB_DIR / 'stock.db'
STATE_FILE = DB_DIR / 'backfill_daily_state.json'
SLEEP_BASE = 0.4
START_DATE = "20251101"
BATCH_SAVE = 50
BATCH_REST = 200


def get_all_stocks(conn):
    return [r[0] for r in conn.execute(
        "SELECT stock_code FROM stock_info ORDER BY stock_code"
    ).fetchall()]


def get_existing_coverage(conn):
    today = date.today().isoformat()
    coverage = {}
    rows = conn.execute(f"""
        SELECT stock_code, COUNT(*), MAX(date) 
        FROM stock_daily 
        WHERE date < '{today}'
        GROUP BY stock_code
    """).fetchall()
    for code, cnt, max_dt in rows:
        coverage[code] = (cnt, str(max_dt))
    return coverage


def code_to_sina(code):
    if code.startswith('6') or code.startswith('68'):
        return f"sh{code}"
    elif code.startswith('0') or code.startswith('3'):
        return f"sz{code}"
    elif code.startswith('4') or code.startswith('8') or code.startswith('9'):
        return f"bj{code}"
    return f"sh{code}"


def fetch_one(code):
    symbol = code_to_sina(code)
    try:
        df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
        if df is None or df.empty:
            return None, "无数据"
        start_dt = datetime.strptime(START_DATE, "%Y%m%d").date()
        df = df[df['date'] >= start_dt].copy()
        if df.empty:
            return None, "无初始数据"
        return df, None
    except Exception as e:
        return None, str(e)[:100]


def parse_akshare_row(df):
    rows = []
    for _, row in df.iterrows():
        try:
            dt = str(row.get('date', ''))[:10]
            if not dt:
                continue
            op = float(row.get('open', 0))
            close = float(row.get('close', 0))
            high = float(row.get('high', 0))
            low = float(row.get('low', 0))
            vol = int(float(row.get('volume', 0))) // 100
            amount = float(row.get('amount', 0))
            turnover = float(row.get('turnover', 0)) * 100
            rows.append((dt, op, close, high, low, vol, amount, 0.0, 0.0, turnover))
        except:
            continue
    return rows


def main():
    resume = '--resume' in sys.argv
    force = '--force' in sys.argv

    state = {"done": [], "failed": [], "total": 0}
    if resume and STATE_FILE.exists():
        with open(STATE_FILE) as f:
            state = json.load(f)
        print(f"断点续传: 已完成{len(state['done'])}只, 失败{len(state.get('failed',[]))}只")

    conn = duckdb.connect(str(DB_PATH))
    all_codes = get_all_stocks(conn)
    print(f"总股票: {len(all_codes)}")

    coverage = get_existing_coverage(conn)
    print(f"已有历史数据: {len(coverage)}只")

    if force:
        to_process = all_codes
        print("强制全量重拉")
    else:
        to_process = []
        for code in all_codes:
            cnt, _ = coverage.get(code, (0, ""))
            if cnt < 60:
                to_process.append(code)
        print(f"需补充: {len(to_process)}只 ({len(all_codes)-len(to_process)}只已有足够数据)")

    done_set = set(state.get("done", []))
    failed_set = set(state.get("failed", []))
    to_process = [c for c in to_process if c not in done_set and c not in failed_set]
    print(f"本次处理: {len(to_process)}只")

    if not to_process:
        print("全部已完成!")
        conn.close()
        return

    state["total"] = len(to_process)
    success = fail = 0
    today_str = date.today().isoformat()

    for i, code in enumerate(to_process):
        print(f"\n[{i+1}/{len(to_process)}] {code}...", end=" ", flush=True)

        df, err = fetch_one(code)
        if err:
            print(f"X {err}")
            state.setdefault("failed", []).append(code)
            fail += 1
        elif df is None or df.empty:
            print("O 无数据")
            state.setdefault("failed", []).append(code)
            fail += 1
        else:
            rows = parse_akshare_row(df)
            if rows:
                conn.execute("BEGIN TRANSACTION")
                inserted = 0
                for r in rows:
                    dt, op, cp, hp, lp, vol, amt, amp, chg, tr = r
                    if dt == today_str:
                        conn.execute(f"""
                            UPDATE stock_daily SET open={op}, close={cp}, high={hp}, low={lp},
                                volume={vol}, amount={amt}, amplitude={amp}, change_pct={chg}, turn_rate={tr}
                            WHERE stock_code='{code}' AND date='{dt}'
                        """)
                        if conn.execute(f"SELECT changes()").fetchone()[0] == 0:
                            conn.execute(f"""
                                INSERT INTO stock_daily 
                                VALUES ('{code}', '{dt}', {op}, {cp}, {hp}, {lp}, {vol}, {amt}, {amp}, {chg}, {tr})
                            """)
                        inserted += 1
                    else:
                        conn.execute(f"""
                            INSERT OR REPLACE INTO stock_daily 
                            (stock_code, date, open, close, high, low, volume, amount, amplitude, change_pct, turn_rate)
                            VALUES ('{code}', '{dt}', {op}, {cp}, {hp}, {lp}, {vol}, {amt}, {amp}, {chg}, {tr})
                        """)
                        inserted += 1
                conn.execute("COMMIT")
                print(f"V {inserted}条")
                state.setdefault("done", []).append(code)
                success += 1
            else:
                print("O 解析0条")
                state.setdefault("failed", []).append(code)
                fail += 1

        if (i + 1) % BATCH_SAVE == 0 or (i + 1) == len(to_process):
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)

        time.sleep(SLEEP_BASE + random.uniform(0, 0.2))
        if (i + 1) % BATCH_REST == 0:
            print(f"  Z 休息10秒防封...", flush=True)
            time.sleep(10)

    total_rows = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    max_date = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    today_cnt = conn.execute(f"SELECT COUNT(*) FROM stock_daily WHERE date='{today_str}'").fetchone()[0]

    print(f"\n{'='*50}")
    print(f"完成! 成功:{success} 失败:{fail}")
    print(f"累计: 成功{len(state['done'])} 失败{len(state.get('failed',[]))}")
    print(f"数据库: 共{total_rows}条, 最新{max_date}({today_cnt}只)")

    for code in ['001288', '002475', '002129', '002346']:
        cnt = conn.execute(f"SELECT COUNT(*) FROM stock_daily WHERE stock_code='{code}'").fetchone()[0]
        dt_range = conn.execute(f"SELECT MIN(date), MAX(date) FROM stock_daily WHERE stock_code='{code}'").fetchone()
        print(f"  {code}: {cnt}条 ({dt_range[0]} ~ {dt_range[1]})")

    conn.close()


if __name__ == '__main__':
    main()
