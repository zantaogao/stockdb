#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读补充查询 2026-09-14 夜报 (cron, 只读)"""
import os, sqlite3, json
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
import duckdb

print("=" * 60)
print("A. 指数近5日 (index_daily_raw)")
print("=" * 60)
con = duckdb.connect('tushare.db', read_only=True)
for code, name in [('000852.SH', '中证1000'), ('000001.SH', '上证指数'), ('399001.SZ', '深证成指'), ('399006.SZ', '创业板指')]:
    try:
        rows = con.execute("""
            SELECT trade_date, close, pct_chg FROM index_daily_raw
            WHERE ts_code=? ORDER BY trade_date DESC LIMIT 5
        """, [code]).fetchall()
        if not rows:
            print(f"{name} {code}: 无数据")
            continue
        print(f"{name} {code}:")
        for d, c, p in rows:
            print(f"   {d}  close={c:.2f}  pct={p:+.2f}%")
    except Exception as e:
        print(f"{name} {code}: ERR {e}")

# 中证1000 20日高低 + MA
print()
print("--- 中证1000 近20日结构 ---")
try:
    rows = con.execute("""
        SELECT trade_date, close, pct_chg FROM index_daily_raw
        WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 25
    """).fetchall()
    closes = [r[1] for r in rows]
    ma5 = sum(closes[:5]) / 5
    ma10 = sum(closes[:10]) / 10
    ma20 = sum(closes[:20]) / 20
    hi20 = max(closes[:20]); lo20 = min(closes[:20])
    print(f"最新 {rows[0][0]} close={closes[0]:.2f}  MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}")
    print(f"20日高 {hi20:.2f}  20日低 {lo20:.2f}  距20日高 {(closes[0]/hi20-1)*100:+.2f}%")
    print("近10日 pct: " + " ".join(f"{r[0][4:]}:{r[2]:+.2f}" for r in rows[:10]))
except Exception as e:
    print("ERR", e)

print()
try:
    rows = con.execute("""
        SELECT trade_date, close, pct_chg FROM index_daily_raw
        WHERE ts_code='000001.SH' ORDER BY trade_date DESC LIMIT 25
    """).fetchall()
    closes = [r[1] for r in rows]
    ma5 = sum(closes[:5]) / 5
    ma10 = sum(closes[:10]) / 10
    ma20 = sum(closes[:20]) / 20
    hi20 = max(closes[:20]); lo20 = min(closes[:20])
    print(f"上证 最新 {rows[0][0]} close={closes[0]:.2f}  MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}")
    print(f"20日高 {hi20:.2f}  20日低 {lo20:.2f}  距20日高 {(closes[0]/hi20-1)*100:+.2f}%")
    print("近10日 pct: " + " ".join(f"{r[0][4:]}:{r[2]:+.2f}" for r in rows[:10]))
except Exception as e:
    print("ERR", e)
con.close()

print()
print("=" * 60)
print("B. 主账户持仓 风控距离 (ledger.db) / watchlist")
print("=" * 60)
lc = sqlite3.connect('ledger.db')
lc.row_factory = sqlite3.Row
try:
    cols = [r[1] for r in lc.execute("PRAGMA table_info(holdings)").fetchall()]
    print("holdings cols:", cols)
    for r in lc.execute("SELECT * FROM holdings").fetchall():
        d = dict(r)
        print(json.dumps(d, ensure_ascii=False, default=str))
except Exception as e:
    print("holdings ERR", e)
print("---- watchlist ----")
try:
    cols = [r[1] for r in lc.execute("PRAGMA table_info(watchlist)").fetchall()]
    print("watchlist cols:", cols)
    for r in lc.execute("SELECT * FROM watchlist ORDER BY rowid DESC LIMIT 20").fetchall():
        print(json.dumps(dict(r), ensure_ascii=False, default=str))
except Exception as e:
    print("watchlist ERR", e)
print("---- strategy_accounts_meta ----")
try:
    for r in lc.execute("SELECT * FROM strategy_accounts_meta").fetchall():
        print(json.dumps(dict(r), ensure_ascii=False, default=str)[:1500])
except Exception as e:
    print("meta ERR", e)
print("---- position_peaks ----")
try:
    for r in lc.execute("SELECT * FROM position_peaks ORDER BY rowid DESC LIMIT 40").fetchall():
        print(json.dumps(dict(r), ensure_ascii=False, default=str))
except Exception as e:
    print("peaks ERR", e)
lc.close()

print()
print("=" * 60)
print("C. 策略账户重评日 / 空仓?")
print("=" * 60)
try:
    lc = sqlite3.connect('ledger.db')
    lc.row_factory = sqlite3.Row
    rows = lc.execute("SELECT * FROM strategy_accounts_meta").fetchall()
    for r in rows:
        d = dict(r)
        aid = d.get('account_id') or d.get('id')
        cfg = d.get('config_json')
        try:
            cfgd = json.loads(cfg) if cfg else {}
        except Exception:
            cfgd = {'raw': cfg}
        print(f"{aid}: last_rebalance={cfgd.get('last_rebalance_date')} keys={list(cfgd.keys())[:12]}")
    lc.close()
except Exception as e:
    print("ERR", e)
