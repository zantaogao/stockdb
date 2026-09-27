#!/usr/bin/env python3
"""A股交易日历硬闸（2026-09-25 调休休市误交易事故后建）

事故：中秋调休，2026-09-25（周五）休市，但盘中链路 cron 排班只有"周一到周五"
表达式（*/10 9-11 * * 1-5），整条链路没有任何一处查交易日历，照常跑了盘中决策
并落了 2 笔主账户成交。国庆/春节整周都落周末所以从未暴露，调休周中休市第一次穿帮。

口径：tushare pro.trade_cal（SSE）为唯一权威源，is_open=0 即非交易日。
缓存：tushare.db 表 trade_cal_cache（拉一次存一年+，之后本地查，不耗 tushare 积分）。
降级：tushare 拉不到且缓存无当日行时，按"周末休市+缓存里该月有数据则信任缓存"处理；
      缓存和 API 都不可用 → 返回 True（宁可多跑一轮决策，不静默漏掉真交易日），
      由调用方的时段闸兜底。

用法（所有盘中脚本 main() 开头）：
    from core.trade_calendar import assert_trading_day
    assert_trading_day()   # 非交易日打日志并 sys.exit(0)
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path('/Users/zantao/.hermes/stockdb')
LEDGER_DB = BASE / 'ledger.db'


def _token():
    cfg = json.loads((BASE / 'config.json').read_text())
    tok = [None]

    def dig(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if 'token' in k.lower() and isinstance(v, str) and len(v) > 10:
                    tok[0] = v
                dig(v)
    dig(cfg)
    return tok[0]


def _ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS trade_cal (
        cal_date TEXT PRIMARY KEY,   -- YYYYMMDD
        is_open INTEGER NOT NULL,    -- 1=交易日 0=休市
        updated_at TEXT NOT NULL)""")


def _refresh(conn, start: str, end: str):
    """从 tushare 拉 [start,end] 日历写缓存表。失败静默（降级路径兜底）。"""
    tok = _token()
    if not tok:
        return
    try:
        import tushare as ts
        pro = ts.pro_api(tok)
        df = pro.trade_cal(exchange='SSE', start_date=start, end_date=end)
        now = datetime.now().isoformat(timespec='seconds')
        with conn:  # 原子事务
            for _, row in df.iterrows():
                conn.execute(
                    "INSERT OR REPLACE INTO trade_cal VALUES (?,?,?)",
                    (str(row['cal_date']), int(row['is_open']), now))
    except Exception as e:
        print(f"  ⚠️ trade_cal 刷新失败（用缓存兜底）: {e}")


def is_trading_day(now: datetime = None) -> bool:
    """当天是否 A 股交易日（tushare trade_cal 权威）。"""
    now = now or datetime.now()
    d = now.strftime('%Y%m%d')
    conn = sqlite3.connect(str(LEDGER_DB), timeout=30)
    try:
        _ensure_table(conn)
        row = conn.execute("SELECT is_open FROM trade_cal WHERE cal_date=?", (d,)).fetchone()
        if row is None:
            # 缓存缺当日：拉当年全年+次年头一月（覆盖年末调休）
            _refresh(conn, f'{d[:4]}0101', f'{int(d[:4]) + 1}0131')
            row = conn.execute("SELECT is_open FROM trade_cal WHERE cal_date=?", (d,)).fetchone()
        if row is None:
            # API 也不通：周末必休，工作日放行（由时段闸兜底），不静默漏交易日
            return now.weekday() < 5
        return row[0] == 1
    finally:
        conn.close()


def is_trading_date(ymd: str) -> bool:
    """⚠️ 与 is_trading_day(now) 不同：回答"任意历史/未来日期 ymd(YYYYMMDD) 是否交易日"。
    数据更新链按天循环拉数用它跳过休市日（09-27 加：休市日对 0 行误判"上游未算完"
    干等 3×60s 重试，09-25 事故复盘）。缓存缺该日 → 自动 _refresh 拉 [当年1/1, 次年1/31]。
    缓存和 API 都查不到 → 返回 True（保守：当作交易日照常拉，不静默漏数）。"""
    d = str(ymd).replace('-', '')
    conn = sqlite3.connect(str(LEDGER_DB), timeout=30)
    try:
        _ensure_table(conn)
        row = conn.execute("SELECT is_open FROM trade_cal WHERE cal_date=?", (d,)).fetchone()
        if row is None:
            _refresh(conn, f'{d[:4]}0101', f'{int(d[:4]) + 1}0131')
            row = conn.execute("SELECT is_open FROM trade_cal WHERE cal_date=?", (d,)).fetchone()
        if row is None:
            return True
        return row[0] == 1
    finally:
        conn.close()


def assert_trading_day(tag: str = ''):
    """非交易日：打日志并退出进程（exit 0，cron 记 completed，不算失败）。"""
    now = datetime.now()
    if is_trading_day(now):
        return
    print(f"[{now.strftime('%H:%M:%S')}] 🚫 非交易日（tushare trade_cal 权威），跳过{tag}")
    sys.exit(0)


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y%m%d')
    dt = datetime.strptime(d, '%Y%m%d')
    conn = sqlite3.connect(str(LEDGER_DB), timeout=30)
    _ensure_table(conn)
    if conn.execute("SELECT COUNT(*) FROM trade_cal").fetchone()[0] == 0:
        _refresh(conn, f'{d[:4]}0101', f'{int(d[:4]) + 1}0131')
    conn.close()
    print(f'{d} is_trading_day =', is_trading_day(dt))
