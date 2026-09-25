#!/usr/bin/env python3
"""交易系统全链路健康检查独立复验脚本（8 链全查）。
用法: 在 ~/.hermes/stockdb 下运行  python3 -B scripts/health_verify.py
exit 0 = 全部通过；exit 1 = 有问题（打印具体项）。

为什么需要它: check_and_alert.sh 的所有检查段都是 `out=$(python3 -c "..." 2>/dev/null)`，
python3 崩溃（import 失败等）时 out 为空 → 无告警、exit 0，看起来健康实则全链路没查（假健康）。
本脚本独立复验关键表 + 判据速查。
"""
import sqlite3, datetime, os, sys

BASE = os.path.expanduser("~/.hermes/stockdb")
STATE_DB = os.path.join(BASE, "signals.db")  # v2温层
TUSHARE_DB = os.path.join(BASE, "tushare.db")
problems = []

def check(name, ok, detail=""):
    print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        problems.append(f"{name}: {detail}")

# 1. 环境
import duckdb
print("[env] duckdb", duckdb.__version__, "| sqlite3 OK")

# 2. signals.db 完整性（v2温层）
c = sqlite3.connect(STATE_DB, timeout=5)
check("signals.db integrity", c.execute("PRAGMA integrity_check").fetchone()[0] == "ok")

# 3. tushare.db 魔数 + daily 新鲜度（DuckDB 魔数在 offset 8，= 4455434b / 'DUCK'）
with open(TUSHARE_DB, "rb") as f:
    f.seek(8)
    magic = f.read(4).hex()
check("tushare.db magic", magic == "4455434b", f"magic={magic}")
conn = duckdb.connect(TUSHARE_DB, read_only=True)
latest = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
delta = (datetime.datetime.now() - datetime.datetime.strptime(str(latest), "%Y%m%d")).days if latest else 999
check("daily 新鲜度", latest is not None and delta <= 10, f"最新 {latest}, {delta} 天前")
for tbl in ["daily", "daily_basic", "stk_limit", "money_flow", "adj_factor"]:
    cnt = conn.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]
    check(f"{tbl} 行数", cnt >= 5000000, f"{cnt:,}")
stocks = conn.execute("SELECT count(*) FROM stock_basic").fetchone()[0]
check("stock_basic 股票数", stocks >= 4000, f"{stocks}")

# 4. ETF NAV 链 —— 真源判据是 fund_daily（etf_scores.scan_date 不动是设计，别拿它判健康）
fd_max = conn.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()[0]
fd_delta = (datetime.datetime.now() - datetime.datetime.strptime(str(fd_max), "%Y%m%d")).days if fd_max else 999
check("fund_daily NAV 新鲜度", fd_delta <= 5, f"最新 {fd_max}, {fd_delta} 天前")
conn.close()

# 5. 评分链
latest_sh = c.execute('SELECT MAX(REPLACE(date,"-","")) FROM signal_history').fetchone()[0]
check("signal_history 有数据", latest_sh is not None)
if latest_sh:
    cnt = c.execute('SELECT count(*) FROM signal_history WHERE REPLACE(date,"-","")=?', [latest_sh]).fetchone()[0]
    check("signal_history 当日行数", 4000 <= cnt <= 6000, f"{latest_sh}: {cnt}")
    # 2026-09-18 改口径：原为 "总行数 <= 200000" 静态阈值。signal_history 是每天 +~4930 行的
    # 增长型表，静态总量阈值必然被正常增长撞穿（越线后每晚固定 FAIL，无信息量）。
    # 改为原意等价的两条：① 近30交易日重复检测 ② 交易日数 x 6000 动态上限。
    dup = c.execute("SELECT count(*) FROM (SELECT 1 FROM signal_history WHERE REPLACE(date,'-','') IN "
                    "(SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY 1 DESC LIMIT 30) "
                    "GROUP BY REPLACE(date,'-',''), stock_code HAVING count(*) > 1)").fetchone()[0]
    check("signal_history 重复行(近30日)", dup == 0, f"{dup} 组" if dup else "无")
    uniq_sh = c.execute("SELECT count(*) FROM (SELECT 1 FROM signal_history GROUP BY REPLACE(date,'-',''), stock_code)").fetchone()[0]
    day_sh = c.execute("SELECT count(DISTINCT REPLACE(date,'-','')) FROM signal_history").fetchone()[0]
    check("signal_history 总量(交易日x6000)", uniq_sh <= day_sh * 6000, f"{uniq_sh:,} / 上限 {day_sh * 6000:,}")
    _idx = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='signal_history' AND name LIKE 'ux_%'").fetchall()]
    check("signal_history 唯一索引", bool(_idx), ",".join(_idx) if _idx else "缺 ux_signal_history_date_code")
# 6. IC 链 —— ic_daily 最新 = 上一交易日是正确状态（IC 需次日收益，当日 IC 下个交易日才能算）
for tbl, col in [("ic_daily", "signal_date"), ("factor_ic_roll", "as_of_date")]:
    try:
        mx = c.execute(f"SELECT MAX({col}) FROM {tbl}").fetchone()[0]
        print(f"[info] {tbl} 最新 {col}: {mx}")
    except Exception as e:
        check(f"{tbl} 查询", False, str(e)[:60])
try:
    # factor_ic_daily 的列是 date（不是 signal_date/calc_date）
    fid = c.execute("SELECT MAX(date) FROM factor_ic_daily").fetchone()[0]
    print(f"[info] factor_ic_daily 最新 date: {fid}")
except Exception as e:
    check("factor_ic_daily 查询", False, str(e)[:60])
c.close()

# 7. 模型链
for m in ["lgb_reg_10d_v3.txt", "lgb_reg_20d_tushare_v13_opt.txt", "lgb_reg_20d_mac_v1.txt",
          "lgb_reg_40d_new_stkfactor.txt", "lgb_reg_etf_20d_v1.txt"]:
    p = os.path.join(BASE, "models", m)
    if os.path.exists(p):
        print(f"[model] {m}: {os.path.getsize(p):,}B")
    else:
        check("模型存在", False, m)

# 8. 备份链
# 2026-09-11 口径修正：本机 backup.sh 把 tushare 快照写进 db_backups/tushare/<YYYYMMDD>/tushare.db
# （每日硬链接增量快照，永久保留），原检查只认顶层 db_backups/tushare.db.*.bak → 每晚误报「无 tushare.db 备份」。
# 现两种布局都认，取最新快照判新鲜度。
bak_dir = os.path.join(BASE, "db_backups")
snaps = []
ts_root = os.path.join(bak_dir, "tushare")
if os.path.isdir(ts_root):
    for d in sorted(os.listdir(ts_root)):
        p_snap = os.path.join(ts_root, d, "tushare.db")
        if os.path.isfile(p_snap):
            snaps.append(p_snap)
if os.path.isdir(bak_dir):
    snaps += [os.path.join(bak_dir, f) for f in sorted(os.listdir(bak_dir))
              if f.startswith("tushare.db.") and f.endswith(".bak")]
if snaps:
    newest = max(snaps, key=os.path.getmtime)
    age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(newest))).days
    check("备份新鲜度", age <= 7,
          f"{os.path.relpath(newest, BASE)} {age} 天前 ({os.path.getsize(newest)/2**30:.1f}G)")
else:
    check("备份存在", False, "db_backups 无 tushare 快照（tushare/<日期>/tushare.db 或 tushare.db.*.bak）")

print("\n===== 结果 =====")
if problems:
    for p in problems:
        print(" -", p)
    sys.exit(1)
print("全部检查通过")
