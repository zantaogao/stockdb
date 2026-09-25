#!/usr/bin/env python3
"""盘中意见-结果回填（方案1：只评估不接管）。

每日收盘后运行：对 analysis/opinion_log.jsonl 中每条意见，
用 tushare.db stock_daily 日线回填发出后 T+1 / T+3 收盘价相对发出价的涨跌幅，
写入 signals.db 表 opinion_feedback（幂等：已有行不重复插，缺天补天）。

口径：
- buyzone  买入区建议 → ret = 之后收盘价较发出价（正=建议正确）
- chase    追高警告   → ret（负=警告正确）
- stopbuy  停买建议   → ret（负=躲过下跌，正确）
- sl/nsl   止损/新止损建议 → ret（负=卖对了）
- tgt      到达目标提示 → ret
无当条数据（停牌/缺日线）时字段留 NULL，下次再补。
"""
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOG = BASE / "analysis" / "opinion_log.jsonl"
SIGNALS = BASE / "signals.db"
TUSHARE = BASE / "tushare.db"


def load_opinions():
    rows = {}
    if not LOG.exists():
        return rows
    for line in LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = d.get("key", "")
        typ = key.split("|")[0]
        if typ not in ("buyzone", "chase", "stopbuy", "sl", "nsl", "tgt"):
            continue
        date = d.get("ts", "")[:10]  # 2026-08-31
        code = d.get("code", "")
        price = d.get("price")
        if not (date and code and price):
            continue
        # 同日同票同类型只留首条（与发出端去重口径一致）
        k = (date, code, typ)
        if k not in rows:
            rows[k] = {"date": date, "code": code, "type": typ, "price": float(price),
                       "text": d.get("text", "")}
    return rows


def future_closes(conn, code, date, n=3):
    """date 之后最多 n 个交易日的收盘价列表（升序）。date 归一化去横杠比较。"""
    d8 = date.replace("-", "")
    rows = conn.execute(
        "SELECT REPLACE(CAST(date AS VARCHAR),'-','') AS d, close FROM stock_daily "
        "WHERE stock_code = ? AND REPLACE(CAST(date AS VARCHAR),'-','') > ? "
        "ORDER BY d LIMIT ?", [code, d8, n]).fetchall()
    return [close for _, close in rows]


def main():
    import duckdb
    # 交易日历硬闸（2026-09-25 调休休市误交易事故）：休市日无盘中意见，不回填
    sys.path.insert(0, str(BASE))
    from core.trade_calendar import assert_trading_day
    assert_trading_day('盘中意见回填')
    opinions = load_opinions()
    if not opinions:
        print("无意见记录")
        return

    ts = duckdb.connect(str(TUSHARE), read_only=True)
    sig = sqlite3.connect(SIGNALS)
    sig.execute("""
        CREATE TABLE IF NOT EXISTS opinion_feedback (
            date TEXT, code TEXT, type TEXT, price REAL,
            close_t1 REAL, close_t3 REAL,
            ret_t1 REAL, ret_t3 REAL,
            backfilled_at TEXT,
            PRIMARY KEY (date, code, type)
        )""")

    existing = {(r[0], r[1], r[2]): (r[3], r[4]) for r in sig.execute(
        "SELECT date, code, type, close_t1, close_t3 FROM opinion_feedback")}

    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = updated = 0
    for (date, code, typ), o in opinions.items():
        have_t1, have_t3 = existing.get((date, code, typ), (None, None))
        closes = []
        if have_t1 is None or have_t3 is None:
            closes = future_closes(ts, code, date, 3)
        c1 = have_t1 if have_t1 is not None else (closes[0] if len(closes) >= 1 else None)
        c3 = have_t3 if have_t3 is not None else (closes[2] if len(closes) >= 3 else None)
        if c1 is None and c3 is None:
            continue  # 日线还没到，下次再补
        r1 = round((c1 / o["price"] - 1) * 100, 2) if c1 else None
        r3 = round((c3 / o["price"] - 1) * 100, 2) if c3 else None
        sig.execute(
            """INSERT INTO opinion_feedback
               (date, code, type, price, close_t1, close_t3, ret_t1, ret_t3, backfilled_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(date, code, type) DO UPDATE SET
                 close_t1=excluded.close_t1, close_t3=excluded.close_t3,
                 ret_t1=excluded.ret_t1, ret_t3=excluded.ret_t3,
                 backfilled_at=excluded.backfilled_at""",
            (date, code, typ, o["price"], c1, c3, r1, r3, now))
        if (date, code, typ) in existing:
            updated += 1
        else:
            inserted += 1
    sig.commit()

    # 汇总（有 T+3 结果的才算样本）
    summary = sig.execute("""
        SELECT type, COUNT(*),
               SUM(CASE WHEN ret_t3 < 0 THEN 1 ELSE 0 END),
               AVG(ret_t3)
        FROM opinion_feedback WHERE ret_t3 IS NOT NULL
        GROUP BY type""").fetchall()
    lines = [f"意见回填: 新增{inserted} 补全{updated} (共{sig.execute('SELECT COUNT(*) FROM opinion_feedback').fetchone()[0]}条)"]
    for typ, n, neg, avg in summary:
        # buyzone 正确=涨(ret>0)；其余正确=跌(ret<0)
        if typ == "buyzone":
            win = n - neg
            label = "买入区"
        else:
            win = neg
            label = {"chase": "追高警告", "stopbuy": "停买", "sl": "止损",
                     "nsl": "新止损", "tgt": "达标提示"}.get(typ, typ)
        lines.append(f"{label}: T+3胜率 {win}/{n} ({win/n*100:.0f}%) 均收益 {avg:+.2f}%")
    pending = sig.execute(
        "SELECT COUNT(*) FROM opinion_feedback WHERE ret_t3 IS NULL").fetchone()[0]
    lines.append(f"待补全(T+3未满): {pending}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()