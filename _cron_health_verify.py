#!/usr/bin/env python3
"""独立健康验证：确认 check_and_alert.sh 的静默退出是真健康而非假阴性"""
import sqlite3, duckdb, os, datetime, json, glob

BASE = "/Users/zantao/.hermes/stockdb"
issues = []
notes = []

def check(name, ok, detail):
    if ok:
        notes.append(f"OK   {name}: {detail}")
    else:
        issues.append(f"FAIL {name}: {detail}")

# ── 1. DB 层 ──
tdb = os.path.join(BASE, "tushare.db")
sdb = os.path.join(BASE, "state.db")

# tushare.db 魔数
with open(tdb, "rb") as f:
    f.seek(8)
    magic = f.read(4).hex().upper()
check("tushare.db 魔数", magic == "4455434B", f"magic={magic}")
tsize = os.path.getsize(tdb)
check("tushare.db 体积", tsize >= 1_000_000_000, f"{tsize/1e9:.2f}GB")

# state.db 完整性
try:
    c = sqlite3.connect(sdb, timeout=5)
    r = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    check("state.db 完整性", r == "ok", r)
except Exception as e:
    check("state.db 完整性", False, str(e)[:80])
ssize = os.path.getsize(sdb)
check("state.db 体积", ssize >= 1_000_000, f"{ssize/1e6:.1f}MB")

# WAL 残留
for db in (tdb, sdb):
    for ext in (".wal", ".shm"):
        p = db + ext
        if os.path.exists(p):
            age = (datetime.datetime.now().timestamp() - os.path.getmtime(p)) / 3600
            check(f"{os.path.basename(db)}{ext} 残留", age <= 24, f"{age:.0f}h")

# ── 2. 数据链 ──
conn = duckdb.connect(tdb, read_only=True)
latest = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
delta_days = (datetime.date.today() - datetime.datetime.strptime(str(latest), "%Y%m%d").date()).days
check("daily 最新交易日", delta_days <= 10, f"{latest} ({delta_days}天前)")
for tbl, (mn, mx) in {
    "daily": (5_000_000, 50_000_000),
    "daily_basic": (5_000_000, 50_000_000),
    "stk_limit": (10_000_000, 50_000_000),
    "money_flow": (5_000_000, 50_000_000),
    "adj_factor": (5_000_000, 20_000_000),
}.items():
    try:
        cnt = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
        ok = mn <= cnt <= mx
        check(f"tushare {tbl} 行数", ok, f"{cnt:,}")
    except Exception as e:
        check(f"tushare {tbl} 行数", False, str(e)[:60])
try:
    stocks = conn.execute("SELECT count(*) FROM stock_basic").fetchone()[0]
    check("stock_basic 股票数", stocks >= 4000, f"{stocks}")
except Exception as e:
    check("stock_basic 股票数", False, str(e)[:60])
conn.close()

# ── 3. 评分链 ──
c = sqlite3.connect(sdb, timeout=5)
c.row_factory = sqlite3.Row
latest_sig = c.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0]
wd = datetime.date.today().weekday()
expected = datetime.date.today() - datetime.timedelta(days=(3 if wd == 0 else 1))
sig_dt = datetime.datetime.strptime(latest_sig, "%Y%m%d").date()
check("signal_history 新鲜度", sig_dt >= expected, f"最新 {latest_sig}, 期望>={expected}")
cnt = c.execute("SELECT count(*) FROM signal_history WHERE REPLACE(date,'-','')=?", [latest_sig]).fetchone()[0]
check("signal_history 当日行数", 4000 <= cnt <= 6000, f"{cnt}")
total = c.execute("SELECT count(*) FROM signal_history").fetchone()[0]
check("signal_history 总行数", total <= 200_000, f"{total:,}")
flat = c.execute("SELECT count(DISTINCT final_score) FROM signal_history WHERE REPLACE(date,'-','')=?", [latest_sig]).fetchone()[0]
check("final_score 区分度", flat > 1, f"DISTINCT={flat}")
r = c.execute("SELECT MIN(fusion_score), MAX(fusion_score) FROM signal_history WHERE REPLACE(date,'-','')=?", [latest_sig]).fetchone()
check("fusion_score 范围", r[1] - r[0] >= 5 if r[0] is not None else False, f"[{r[0]:.1f}~{r[1]:.1f}]")

# ── 4. 信号链 ──
latest_wl = c.execute("SELECT MAX(REPLACE(scan_date,'-','')) FROM watchlist").fetchone()[0]
if latest_wl:
    lw = datetime.datetime.strptime(latest_wl, "%Y%m%d").date()
    check("watchlist 新鲜度", lw >= expected, f"最新 {latest_wl}, 期望>={expected}")
else:
    check("watchlist 数据", False, "无数据")
pending = c.execute("SELECT count(*) FROM watchlist WHERE status='pending'").fetchone()[0]
check("watchlist pending", pending > 0, f"{pending} 条 pending")
f3 = c.execute("SELECT MAX(REPLACE(date,'-','')), count(*) FROM fusion_3f_signals").fetchone()
if f3[0]:
    f3_dt = datetime.datetime.strptime(f3[0], "%Y%m%d").date()
    f3_delta = (datetime.date.today() - f3_dt).days
    check("fusion_3f_signals 新鲜度", f3_delta <= 3, f"最新 {f3[0]} ({f3_delta}天前), {f3[1]}行")
else:
    check("fusion_3f_signals 数据", False, "无数据")
try:
    es = c.execute("SELECT MAX(scan_date), count(*) FROM etf_scores").fetchone()
    if es[0]:
        es_delta = (datetime.date.today() - datetime.date.fromisoformat(es[0])).days
        check("etf_scores 新鲜度", es_delta <= 5, f"最新 {es[0]} ({es_delta}天前)")
    else:
        check("etf_scores 数据", False, "无数据")
except Exception as e:
    check("etf_scores 数据", False, str(e)[:60])

# ── 5. 风控链 ──
pj = os.path.join(BASE, "orders", "pending.json")
if os.path.exists(pj):
    try:
        d = json.load(open(pj))
        sc = len(d.get("signals", []))
        age = (datetime.datetime.now().timestamp() - os.path.getmtime(pj)) / 3600
        check("pending.json 解析", True, f"{sc} 条信号, {age:.1f}h 前写入")
        check("pending.json 过期", not (age > 4 and sc > 0), f"age={age:.1f}h, signals={sc}")
    except Exception as e:
        check("pending.json 解析", False, str(e)[:80])
else:
    notes.append("OK   pending.json 不存在（无待执行订单，正常）")
try:
    bad = c.execute("SELECT count(*) FROM execution_logs WHERE status='FAILED' AND exec_time > datetime('now','-7 days')").fetchone()[0]
    check("execution_logs 失败数", bad <= 3, f"7天内 {bad} 条 FAILED")
except Exception as e:
    notes.append(f"INFO execution_logs 不可访问: {str(e)[:60]}")

# ── 6. IC 监控链 ──
try:
    ic = c.execute("SELECT MAX(signal_date), count(*) FROM ic_daily").fetchone()
    if ic[0]:
        ic_s = str(ic[0])
        ic_dt = datetime.datetime.strptime(ic_s[:10] if "-" in ic_s else ic_s, "%Y-%m-%d" if "-" in ic_s else "%Y%m%d")
        ic_delta = (datetime.datetime.now() - ic_dt).days
        check("ic_daily 新鲜度", ic_delta <= 5, f"最新 {ic[0]} ({ic_delta}天前), {ic[1]}行")
    else:
        check("ic_daily 数据", False, "无数据")
except Exception as e:
    check("ic_daily 数据", False, str(e)[:60])
try:
    fir = c.execute("SELECT MAX(as_of_date), count(*) FROM factor_ic_roll").fetchone()
    check("factor_ic_roll 数据", bool(fir[0]), f"最新 {fir[0]}, {fir[1]}行")
except Exception as e:
    check("factor_ic_roll 数据", False, str(e)[:60])
c.close()

# ── 7. 模型链 ──
for m in ["lgb_reg_10d_v3.txt", "lgb_reg_20d_mac_v1.txt", "lgb_reg_40d_new_stkfactor.txt", "lgb_reg_etf_20d_v1.txt"]:
    p = os.path.join(BASE, "models", m)
    if os.path.exists(p):
        sz = os.path.getsize(p)
        check(f"模型 {m}", sz >= 10_000, f"{sz/1024:.0f}KB")
    else:
        check(f"模型 {m}", False, "不存在")

# ── 8. 备份链 ──
baks = sorted(glob.glob(os.path.join(BASE, "db_backups", "tushare.db.*.bak")), key=os.path.getmtime, reverse=True)
if baks:
    age_days = (datetime.datetime.now().timestamp() - os.path.getmtime(baks[0])) / 86400
    check("备份新鲜度", age_days <= 7, f"最新 {os.path.basename(baks[0])} ({age_days:.1f}天前)")
else:
    check("备份", False, "db_backups 无 tushare.db 备份")

print("=" * 60)
print(f"验证时间: {datetime.datetime.now():%Y-%m-%d %H:%M} (周{datetime.date.today().isoweekday()})")
print(f"独立验证: {len(notes)} 项通过 / {len(issues)} 项异常")
print("=" * 60)
for n in notes:
    print(n)
for i in issues:
    print(i)
if issues:
    print(f"\n>>> 共 {len(issues)} 项异常，需人工处理")
else:
    print("\n>>> 全部通过：check_and_alert.sh 静默退出 = 真健康")
