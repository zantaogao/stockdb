#!/usr/bin/env python3
"""_audit_scan_rules.py — 静态穷举扫描：按已知 bug 类别过一遍生产代码（只读，不改任何东西）。
输出 JSON 到 stdout 供复核。误报难免，全部 findings 都要实数据复核后才算数。
规则集来自 quant-pipeline-audit skill 的实锤 bug 类别。"""
import json, os, re, sys
from pathlib import Path

ROOT = Path(os.path.expanduser("~/.hermes/stockdb"))
# 扫描范围：生产代码 = core/ agents/ scripts/*.py 根目录 .py + ~/.hermes/scripts/*.sh 包装
targets = []
for d in ["core", "agents"]:
    targets += sorted((ROOT / d).glob("*.py"))
targets += sorted(ROOT.glob("*.py"))
targets += sorted((ROOT / "scripts").glob("*.py"))
targets = [t for t in targets if ".bak" not in t.name and "_cron_" not in t.name
           and not t.name.startswith(("_chk_", "_check_", "_verify", "_audit", "_scan", "_q_"))]

findings = []
def add(rule, path, line_no, line, note=""):
    findings.append({"rule": rule, "file": str(path.relative_to(ROOT.parent)),
                     "line": line_no, "text": line.strip()[:160], "note": note})

# 已知合法的列名（_bfq 在 stk_factor.extra 里合法，出现在 SQL 直接列上才可疑）
BARE_FACTOR_COLS = ["kdj_k", "cci", "rsi_12", "rsi_6", "rsi_24", "atr", "macd_dif", "mfi", "cco"]

for p in targets:
    try:
        src = p.read_text(errors="ignore")
    except Exception as e:
        add("read_fail", p, 0, str(e))
        continue
    lines = src.splitlines()

    # R1: SELECT 列序 vs Python 解包/索引 —— 找 fetchall 后紧跟的 r[N] 密集区，人工对账用：列出含 SELECT 多列 与 同函数 r[数字] 的文件
    select_multi = [(i+1, l) for i, l in enumerate(lines)
                    if re.search(r"\bSELECT\b(?!\s+\*|\s+\w+\()", l, re.I)
                    and l.count(",") >= 3 and "LIMIT 1" not in l.upper()]
    unpack = [(i+1, l) for i, l in enumerate(lines) if re.search(r"=\s*\{?\s*r\[\d\]|\bfor\s+\w+\s+in\s+\w*\.fetchall\(\)", l)]
    if select_multi and unpack:
        add("R1_manual_colcheck", p, select_multi[0][0], select_multi[0][1],
            f"SELECT多列x{len(select_multi)}行, 索引解包x{len(unpack)}行 — 需逐列对账")

    # R2: 位置式 INSERT VALUES (?,?,..) 且无列名清单
    for i, l in enumerate(lines):
        m = re.search(r"INSERT\s+(OR\s+REPLACE\s+|OR\s+IGNORE\s+)?INTO\s+\w+\s+VALUES\s*\(\s*\?", l, re.I)
        if m and "SELECT" not in l.upper():
            add("R2_positional_insert", p, i+1, l, "无列名清单，ADD COLUMN 后静默串列风险")

    # R3: 函数内 import pandas/duckdb/sqlite3（局部遮蔽坑）
    cur_fn = None
    for i, l in enumerate(lines):
        fm = re.match(r"^(def|    def)\s+(\w+)", l)
        if fm: cur_fn = fm.group(2)
        if l.startswith("    ") and re.search(r"^\s{4,}(import\s+(pandas|duckdb|sqlite3)|from\s+(pandas|duckdb)\b)", l):
            add("R3_func_import_shadow", p, i+1, l, f"函数 {cur_fn} 内 import，跨段引用名字会局部化")

    # R4: JOIN 键用 REPLACE/REPLACE 比较
    for i, l in enumerate(lines):
        if re.search(r"JOIN\b", l, re.I) and "REPLACE(" in l.upper():
            add("R4_replace_join", p, i+1, l, "REPLACE JOIN 无索引，109s 实锤过")

    # R5: datetime.now 硬匹配当天
    for i, l in enumerate(lines):
        if re.search(r"now\(\)\.strftime\(['\"]%Y%m%d", l) and "as_of" not in l:
            add("R5_now_today", p, i+1, l, "节假日/数据滞后会误报或算错，应 MAX(date) 自适应")

    # R6: CREATE TABLE IF NOT EXISTS + 主键声明（已存在则 PK 无效）
    for i, l in enumerate(lines):
        if re.search(r"CREATE TABLE IF NOT EXISTS", l, re.I):
            block = "\n".join(lines[i:i+30])
            if re.search(r"PRIMARY KEY", block, re.I):
                add("R6_create_ifnotexists_pk", p, i+1, l, "表已存在时 PK 不生效，INSERT OR REPLACE 退化")

    # R7: SELECT 直接列查 stk_factor 因子列（直接列全 0 陷阱）
    for i, l in enumerate(lines):
        up = l.upper()
        if "STK_FACTOR" in up and "EXTRA" not in up:
            for c in BARE_FACTOR_COLS:
                if re.search(rf"\b{c}\b", l, re.I) and not re.search(rf"{c}_", l, re.I):
                    add("R7_bare_factor_col", p, i+1, l, f"读直接列 {c}：stk_factor 直接列全0，真值在 extra JSON _bfq")
                    break

    # R8: forward_days / 窗口列 —— 该表是否有回填重算（人工判）
    for i, l in enumerate(lines):
        if re.search(r"forward_days", l) and re.search(r"INSERT|CREATE", l, re.I):
            add("R8_forward_window", p, i+1, l, "带窗口IC表：两问——成熟后会覆盖重算吗？统计按定稿窗口过滤了吗？")

    # R9: 模型文件/norm_stats 路径配对（列出所有引用供对账）
    for i, l in enumerate(lines):
        for m in re.finditer(r"(models/[A-Za-z0-9_.\-]+\.(?:txt|json))", l):
            add("R9_model_stat_ref", p, i+1, l.strip()[:100], m.group(1))

# R10: 模型文件 vs norm_stats mtime 配对检查
models_dir = ROOT / "models"
mt = []
for f in sorted(models_dir.iterdir()):
    if f.suffix in (".txt", ".json") and ".bak" not in f.name:
        mt.append({"file": f.name, "mtime": int(f.stat().st_mtime), "size": f.stat().st_size})
mt.sort(key=lambda x: x["file"])

# R11: cron 包装脚本指向的 python 文件是否存在
wrap_dir = Path(os.path.expanduser("~/.hermes/scripts"))
wraps = []
for sh in sorted(wrap_dir.glob("*.sh")):
    body = sh.read_text(errors="ignore")
    for m in re.finditer(r"(?:python3?(?: -B)?\s+)([\w./$~-]+\.py)", body):
        path = m.group(1).replace("$HOME", str(Path.home()))
        if not path.startswith("/"):
            path = str(ROOT / path)
        wraps.append({"sh": sh.name, "py": path, "exists": os.path.exists(path)})

print(json.dumps({"targets": len(targets), "findings": findings,
                  "model_mtimes": mt, "cron_wrappers": wraps}, ensure_ascii=False, indent=1))
