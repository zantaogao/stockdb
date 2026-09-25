#!/usr/bin/env python3
"""
每周全系统健康检查
====================
检查内容:
1. 数据库完整性 (tushare.db, ledger.db, signals.db)
2. 模型文件完整性
3. 模块引用一致性 (scoring.py vs 实际文件)
4. 特征管道一致性
5. 定时任务状态
"""
import sys, json, os, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # stockdb root
sys.path.insert(0, str(BASE))

issues = []
warnings = []
ok_count = 0

def check(name, ok, detail=""):
    global ok_count
    if ok:
        ok_count += 1
        print(f"  ✅ {name}")
    else:
        issues.append(f"{name}: {detail}")
        print(f"  ❌ {name} — {detail}")

def warn(name, detail=""):
    warnings.append(f"{name}: {detail}")
    print(f"  ⚠️  {name} — {detail}")

print("=" * 60)
print("📋 A-Quant 全系统健康检查")
print(f"时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)

# ──────────────────────────────────────────
# 1. 数据库完整性
# ──────────────────────────────────────────
print("\n🔹 1. 数据库完整性")

# tushare.db
tushare_db = BASE / 'tushare.db'
if tushare_db.exists():
    size_mb = tushare_db.stat().st_size / 1024 / 1024
    check("tushare.db 文件存在", True, f"({size_mb:.0f}MB)")
    try:
        import duckdb
        dconn = duckdb.connect(str(tushare_db), read_only=True)
        # DuckDB 不支持 PRAGMA integrity_check，用自检替代
        r = dconn.execute("SELECT 1").fetchone()
        check("tushare.db 可连接", True)
        tables = [r[0] for r in dconn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
        dconn.close()
        required = ['daily', 'stock_basic', 'stk_factor', 'moneyflow_raw', 'adj_factor',
                     'fund_basic', 'fund_daily']
        for t in required:
            check(f"  表 {t} 存在", t in tables, f"缺少{t}")
    except Exception as e:
        warn("tushare.db DuckDB 检查", str(e))
else:
    check("tushare.db 文件存在", False, "文件不存在")

# v2 三层: ledger.db + signals.db（state.db 已冻结为 .pre_split，2026-08-29）
def check_sqlite_db(db_path, name, required):
    if db_path.exists():
        size_mb = db_path.stat().st_size / 1024 / 1024
        check(f"{name} 文件存在", True, f"({size_mb:.0f}MB)")
        try:
            conn = sqlite3.connect(str(db_path), timeout=10)
            conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            check(f"{name} 完整性校验", True)
        except Exception as e:
            check(f"{name} 完整性校验", False, str(e))
        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for t in required:
                if t in tables:
                    cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    check(f"  {name} 表 {t} 存在 ({cnt} 行)", True)
                else:
                    check(f"  {name} 表 {t} 存在", False)
            conn.close()
        except Exception as e:
            warn(f"{name} 表检查", str(e))
    else:
        check(f"{name} 文件存在", False, "文件不存在")

check_sqlite_db(BASE / 'ledger.db', 'ledger.db', ['holdings', 'trade_log', 'watchlist'])
check_sqlite_db(BASE / 'signals.db', 'signals.db', ['signal_history', 'ic_daily', 'etf_ic'])

# ──────────────────────────────────────────
# 2. 模型文件完整性
# ──────────────────────────────────────────
print("\n🔹 2. 模型文件完整性")
model_dir = BASE / 'models'
if model_dir.exists():
    required_models = [
        ('lgb_reg_10d_v3.txt', '10d模型'),
        ('v10_v3_stats.json', '10d统计量'),
        ('lgb_reg_20d_mac_v1.txt', '20d模型'),
        ('v20_mac_v1_stats.json', '20d统计量'),
        ('lgb_reg_40d_new_stkfactor.txt', '40d模型'),
        ('v6_norm_stats_40d_tushare_v2_stkfactor.json', '40d统计量'),
        ('lgb_reg_etf_20d_v1.txt', 'ETF模型'),
        ('v_etf_v1_stats.json', 'ETF统计量'),
    ]
    for fname, label in required_models:
        f = model_dir / fname
        if f.exists():
            sz = f.stat().st_size
            check(f"  {label} ({fname})", sz > 0, f"文件存在 ({sz/1024:.0f}KB)" if sz > 0 else "")
        else:
            check(f"  {label} ({fname})", False, "文件缺失")
else:
    check("models 目录存在", False)

# ──────────────────────────────────────────
# 3. 模块引用一致性
# ──────────────────────────────────────────
print("\n🔹 3. 模块引用一致性")

# 3a. scoring.py 中的模型路径
scoring_py = BASE / 'core' / 'scoring.py'
if scoring_py.exists():
    src = scoring_py.read_text()
    for fname, label in required_models:
        if fname in src:
            check(f"  scoring.py 引用 {label}", True)
        else:
            check(f"  scoring.py 引用 {label}", False, f"文件 {fname} 未被引用")
else:
    check("scoring.py 存在", False)

# 3b. sim_engine.py 模型校验
sim_engine = BASE / 'core' / 'sim_engine.py'
if sim_engine.exists():
    src = sim_engine.read_text()
    if 'lgb_reg_20d_mac_v1.txt' in src:
        check("sim_engine.py 校验引用 20d_mac_v1", True)
    else:
        warn("sim_engine.py 校验引用", "可能还是旧模型名")
else:
    warn("sim_engine.py 不存在", "不影响运行")

# 3c. 特征维度一致性
scoring_src = scoring_py.read_text() if scoring_py.exists() else ""
has_pv = 'PV_INDICES = [' in scoring_src
has_base = 'BASE_KEEP_INDICES = [' in scoring_src
check("  scoring.py 特征定义完整", has_pv and has_base,
      f"PV_INDICES={has_pv}, BASE_KEEP_INDICES={has_base}")

# ──────────────────────────────────────────
# 4. 数据新鲜度
# ──────────────────────────────────────────
print("\n🔹 4. 数据新鲜度")
from datetime import datetime, timedelta
today = datetime.now().strftime('%Y%m%d')

try:
    import duckdb
    dconn = duckdb.connect(str(tushare_db))
    # daily 表
    r = dconn.execute("SELECT MAX(trade_date) FROM daily").fetchone()
    if r and r[0]:
        gap = (datetime.now() - datetime.strptime(str(r[0]), '%Y%m%d')).days
        check(f"  日线数据更新到 {r[0]}", gap <= 5, f"距今 {gap} 天")
    else:
        check("日线数据", False, "无数据")
    r2 = dconn.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()
    if r2 and r2[0]:
        gap2 = (datetime.now() - datetime.strptime(str(r2[0]), '%Y%m%d')).days
        check(f"  ETF净值更新到 {r2[0]}", gap2 <= 5, f"距今 {gap2} 天")
    dconn.close()
except Exception as e:
    warn("数据新鲜度检查", str(e))

try:
    conn = sqlite3.connect(str(state_db), timeout=5)
    r = conn.execute("SELECT MAX(date) FROM signal_history").fetchone()
    if r and r[0]:
        gap3 = (datetime.now() - datetime.strptime(str(r[0])[:8], '%Y%m%d')).days
        check(f"  评分数据更新到 {r[0]}", gap3 <= 5, f"距今 {gap3} 天")
    conn.close()
except Exception as e:
    warn("评分数据新鲜度", str(e))

# ──────────────────────────────────────────
# 5. 定时任务状态 & 脚本路径校验
# ──────────────────────────────────────────
print("\n🔹 5. 定时任务状态")
try:
    cron_json = Path(os.path.expanduser('~/.hermes/cron/jobs.json'))
    if cron_json.exists():
        with open(cron_json) as f:
            data = json.load(f)
        jobs = data.get('jobs', [])
        scripts_dir = Path(os.path.expanduser('~/.hermes/scripts/'))
        for j in jobs:
            name = j.get('name', '?')
            sched = j.get('schedule', {})
            sched_str = sched.get('display', sched.get('expr', '')) if isinstance(sched, dict) else str(sched)
            status = j.get('last_status', None)
            enabled = j.get('enabled', True)
            
            # 状态图标
            if status == 'ok':
                icon = "✅"
            elif status == 'error':
                icon = "❌"
            elif not enabled:
                icon = "⏸️"
            else:
                icon = "⏳"
            
            check(f"  {icon} {name} ({sched_str})", status != 'error', f"状态={status}")
            
            # 检查 no_agent 脚本路径
            script = j.get('script')
            if script:
                script_path = scripts_dir / script
                if script_path.exists():
                    check(f"    ✓ 脚本存在: {script}", True)
                else:
                    check(f"    ✗ 脚本路径错误: {script}", False, 
                          f"解析路径 {script_path} 不存在")
            
            # 检查最近一次输出日志是否有错误
            job_id = j.get('id')
            if job_id:
                out_dir = Path(os.path.expanduser(f'~/.hermes/cron/output/{job_id}'))
                if out_dir.exists() and status == 'error':
                    # 找到最近的输出
                    logs = sorted(out_dir.glob('*.md'), reverse=True)
                    if logs:
                        log_content = logs[0].read_text()
                        if 'Script not found' in log_content or 'Traceback' in log_content:
                            # 提取具体错误
                            for line in log_content.split('\n'):
                                if 'Script not found' in line or 'Traceback' in line:
                                    error_detail = line.strip()[:120]
                                    break
                            else:
                                error_detail = "脚本异常（见日志）"
                            warn(f"  最近错误: {error_detail}")
    else:
        warn("cron/jobs.json 不存在")
except Exception as e:
    warn("定时任务检查", str(e))

# ──────────────────────────────────────────
# 总结
# ──────────────────────────────────────────
print("\n" + "=" * 60)
total = ok_count
fatal = len([i for i in issues if "缺失" in i or "不存在" in i or "校验" in i])
print(f"📊 检查结果：{total} 通过 | {len(issues)} 问题 | {len(warnings)} 警告 | {fatal} 严重")

if issues:
    print("\n🔴 问题列表:")
    for i in issues:
        print(f"  • {i}")

if warnings:
    print("\n🟡 警告:")
    for w in warnings:
        print(f"  • {w}")

if not issues and not warnings:
    print("\n✅ 系统健康，无需处理")
    print("=" * 60)

# 输出JSON供cron调度使用
result = {
    "passed": ok_count,
    "issues": len(issues),
    "warnings": len(warnings),
    "critical": fatal,
    "issue_list": issues,
    "warn_list": warnings,
    "healthy": len(issues) == 0 and len(warnings) == 0,
    "timestamp": datetime.now().isoformat()
}
print(json.dumps(result, ensure_ascii=False))
