#!/usr/bin/env python3
"""
补缺缺失财报数据（v3 - Eastmoney API版）。

用法: python3 scripts/fix_missing_financial.py [--force]
  状态文件: ~/.hermes/stockdb/fix_financial_state.json
  --reset-state: 清空状态

使用 Eastmoney stock_financial_analysis_indicator_em 单API拉取全量历史财务数据，
不依赖Sina（已封IP）。
"""

import duckdb
import akshare as ak
import pandas as pd
import json, sys, time
from pathlib import Path
import random

DB_DIR = Path.home() / '.hermes' / 'stockdb'
DB_PATH = DB_DIR / 'stock.db'
STATE_FILE = DB_DIR / 'fix_financial_state.json'
SLEEP_BASE = 0.6   # 700ms 间隔，慢慢来防封


def code_to_em(code):
    """000690 → 000690.SZ"""
    if code.startswith('6'):
        return f"{code}.SH"
    elif code.startswith('0') or code.startswith('3') or code.startswith('2'):
        return f"{code}.SZ"
    elif code.startswith('4') or code.startswith('8') or code.startswith('9'):
        return f"{code}.BJ"
    return f"{code}.SH"


def code_to_sz(code):
    """000690 → 000690.SZ (深市统一)"""
    if code.startswith('6'):
        return f"{code}.SH"
    return f"{code}.SZ"


def get_missing_stocks(force=False):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    all_stocks = [r[0] for r in con.execute(
        "SELECT stock_code FROM stock_info ORDER BY stock_code"
    ).fetchall()]
    con.close()
    if force:
        return all_stocks
    con = duckdb.connect(str(DB_PATH), read_only=True)
    have_data = set(r[0] for r in con.execute(
        "SELECT DISTINCT stock_code FROM fin_income"
    ).fetchall())
    con.close()
    return [c for c in all_stocks if c not in have_data]


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"done": [], "failed": [], "skipped": []}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def parse_num(val):
    if val is None: return None
    if isinstance(val, (int, float)): return float(val) if not pd.isna(val) else None
    s = str(val).replace(',', '').strip()
    if s in ('--', '', '-', 'NaN', 'None', 'nan'): return None
    try: return float(s)
    except: return None


def fetch_em_data(em_code):
    """使用Eastmoney API拉取全量财务数据"""
    try:
        df = ak.stock_financial_analysis_indicator_em(symbol=em_code, indicator='按报告期')
        if df is None or df.empty:
            return None, "无数据"
        return df, None
    except Exception as e:
        return None, f"API错误: {str(e)[:80]}"


def process_one_stock(code):
    """拉取并写入一只股票"""
    em_code = code_to_em(code)
    print(f"→ {code} ({em_code})...", end=" ", flush=True)

    df, err = fetch_em_data(em_code)
    if err:
        print(f"✗ {err}")
        return False, err
    if df is None or df.empty:
        print("○ 无数据")
        return True, "no_data"

    try:
        con = duckdb.connect(str(DB_PATH))

        income_rows = []
        for _, row in df.iterrows():
            rd = str(row.get('REPORT_DATE', ''))[:10]
            if not rd:
                continue

            revenue = parse_num(row.get('TOTALOPERATEREVE'))
            rev_yoy = parse_num(row.get('TOTALOPERATEREVETZ'))
            profit = parse_num(row.get('PARENTNETPROFIT'))
            profit_yoy = parse_num(row.get('PARENTNETPROFITTZ'))
            gross_margin_ratio = parse_num(row.get('MLR'))  # 毛利率(%)
            net_margin_ratio = parse_num(row.get('XSJLL'))  # 净利率(%)
            eps = parse_num(row.get('EPSJB'))
            roe_val = parse_num(row.get('ROEJQ'))  # ROE(%)

            # 转换为我们的数据库格式
            # gross_margin 存的是小数(如0.234)，Eastmoney返回的是百分比(23.4)
            gm = gross_margin_ratio / 100 if gross_margin_ratio is not None else None
            nm = net_margin_ratio / 100 if net_margin_ratio is not None else None

            income_rows.append((code, rd, revenue, rev_yoy, profit, profit_yoy,
                                gm, nm, eps, roe_val))

        if income_rows:
            con.executemany(
                """INSERT OR IGNORE INTO fin_income
                   (stock_code, report_date, revenue, revenue_yoy, profit, profit_yoy,
                    gross_margin, net_margin, eps, roe)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                income_rows
            )
            con.commit()

        con.close()
        print(f"✓ {len(income_rows)}条")
        return True, f"OK({len(income_rows)})"

    except Exception as e:
        print(f"✗ DB: {e}")
        return False, f"DB: {e}"


def main():
    if '--reset-state' in sys.argv and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("状态已重置")

    force = '--force' in sys.argv
    missing = get_missing_stocks(force)
    if not missing:
        print("没有需要补数据的股票。")
        return

    state = load_state()
    done_set = set(state["done"])
    skipped_set = set(state.get("skipped", []))
    to_process = [c for c in missing if c not in done_set and c not in skipped_set]

    print(f"总缺数据: {len(missing)}, 已完成: {len(done_set)}, 跳过: {len(skipped_set)}, 本次: {len(to_process)}")
    if not to_process:
        print("全部完成！")
        return

    success = fail = no_data = 0

    for i, code in enumerate(to_process):
        print(f"\n[{i+1}/{len(to_process)}] ", end="")
        ok, msg = process_one_stock(code)

        if ok and msg == "no_data":
            state.setdefault("skipped", []).append(code)
            no_data += 1
        elif ok:
            state["done"].append(code)
            success += 1
        else:
            state.setdefault("failed", []).append(code)
            fail += 1

        if (i + 1) % 10 == 0 or (i + 1) == len(to_process):
            save_state(state)

        time.sleep(SLEEP_BASE + random.uniform(0, 0.2))
        
        # 每200只休息10秒，稳一点
        if (i + 1) % 200 == 0:
            print(f"  ⏸ 休息10秒防封...", flush=True)
            time.sleep(10)

    save_state(state)
    print(f"\n{'='*50}")
    print(f"完成! 成功:{success} 无数据:{no_data} 失败:{fail}")
    print(f"累计: 完成{len(state['done'])} 跳过{len(state.get('skipped',[]))} 失败{len(state.get('failed',[]))}")


if __name__ == '__main__':
    main()
