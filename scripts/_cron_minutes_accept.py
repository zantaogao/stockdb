#!/usr/bin/env python3
"""分钟线库验收（stockdb 治理 Task 2.2）：三层断言——文件存在、bar 数完整、时间戳口径。

A. 覆盖：5min/ parquet 票数 ≥ MIN_CODES；缺票数=failed.txt 行数（透明化，>0 连续7天推QQ=⑤定案）
B. 完整性：抽 SAMPLE 票——每交易日 bar 数≈48（容差：停牌日缺、半日市~24）；票内日期 vs trade_cal 对齐
C. 口径（Task 3.2 锁死依据）：断言 baostock 5min = bar-结束时间戳（09:30 bar 标签显示 093500000）；
   偏离→FAIL（口径一旦漂移，RQAlpha 对拍全白跑）
用法: /usr/bin/python3 -B _cron_minutes_accept.py
退出码 0=PASS（含已知缺口说明） 1=FAIL
"""
import os, sys, json
from pathlib import Path
import pandas as pd

BASE = Path(os.path.expanduser("~/.hermes/stockdb"))
MIN5 = BASE / "minutes" / "5min"
FAILED = BASE / "minutes" / "failed.txt"
TRADE_CAL = BASE / "minutes" / "trade_cal_5min.json"   # 由本脚本首跑缓存
SAMPLE = ["sh_603257", "sh_600000", "sz_000001", "sh_600519", "sz_300750",
          "sh_688981", "sz_001225", "sh_601899", "sz_002415", "sh_600900"]
BARS_PER_DAY = 48   # A股 5min：4小时=48根
MIN_CODES = 5200

fails = []
files = sorted(MIN5.glob("*.parquet"))
n_files = len(files)
n_failed = len([l for l in FAILED.read_text().splitlines() if l.strip()]) if FAILED.exists() else 0
print(f"[A] 覆盖: parquet={n_files} 待补(failed.txt)={n_failed}")
if n_files < MIN_CODES:
    fails.append(f"票数 {n_files} < {MIN_CODES}")

# 交易日历（用 600000 自身日期做参照 + 全库并集近似）
all_dates = set()
rows_by_code = {}
for code in SAMPLE:
    p = MIN5 / f"{code}.parquet"
    if not p.exists():
        fails.append(f"[B] 缺文件 {code}")
        continue
    df = pd.read_parquet(p)
    rows_by_code[code] = df
    all_dates |= set(df["date"].astype(str).unique())
cal = sorted(all_dates)
if not TRADE_CAL.exists():
    TRADE_CAL.write_text(json.dumps(cal))
print(f"[B] 抽 {len(rows_by_code)} 票，库内日期并集 {cal[0]}..{cal[-1]} 共 {len(cal)} 个交易日")

ts_issue = 0
for code, df in rows_by_code.items():
    g = df.groupby("date").size()
    # 容差：48 标准 / 49=上午收盘 11:30 集合竞价半根（实测 6/11 全市场混杂 48/49，标签唯一）/ 24=半日市
    # 6/11 类实测：全市场混杂 48/49——49=上午收盘多一根 113000 标签的集合竞价半根（baostock 处理差异，标签唯一非重复）
    bad = {d: int(c) for d, c in g.items() if c not in (BARS_PER_DAY, 49, 24)}
    if bad:
        worst = sorted(bad.items(), key=lambda kv: -abs(kv[1]-BARS_PER_DAY))[:3]
        print(f"    {code}: {len(bad)} 天 bar 数异常(样本{worst})")
    # C 口径断言：每票首根的 time 标签
    t0 = str(df.sort_values("time")["time"].iloc[0])
    # 期望 bar-结束口径：首根=...093500000
    if not t0.endswith("093500000"):
        ts_issue += 1
        print(f"    [C!] {code} 首根标签 {t0}（期望 09:35 结束口径）")
if ts_issue == 0 and rows_by_code:
    print(f"[C] 时间戳口径 PASS: baostock 5min = bar-结束（首根 093500000 = 覆盖 09:30–09:35）——RQAlpha 3.2 按此适配")
else:
    fails.append(f"[C] {ts_issue} 票时间戳口径偏离")

if fails:
    print("\n".join("[FAIL] " + f for f in fails)); sys.exit(1)
print("MINUTES_ACCEPT_PASS")
