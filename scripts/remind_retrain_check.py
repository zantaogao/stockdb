#!/usr/bin/env python3
"""
remind_retrain_check.py — 模型重训提醒检查（remind_retrain.sh 的检查逻辑）

判断依据：
  1. 模型文件年龄：活跃模型超过 MAX_AGE 天 → 考虑重训；超过 2x → 建议立即重训
  2. 模型级 IC：ic_daily 近 N 条均值（ic_reg10/ic_reg20/ic_reg40/ic_fusion）
     - fusion 均值 < 0.03 → 融合模型 IC 走弱
     - reg40 均值 < 0.05 → 40d 模型 IC 走弱
  3. 三因子融合滚动 IC：factor_ic_roll 最新 fusion_3f_score 的 mean_ic < 0 → 融合信号失效率高

输出：检查结果 + 结论（需要重训 / 暂不需要）
退出码：恒为 0（提醒类脚本，结论以输出为准，不让 cron 误报失败）
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'signals.db'  # v2温层

# (模型文件名, 显示名, 重训间隔天数)
# 2026-08-07 用户拍板：日历间隔与预测窗口匹配——预测窗口越短，风格漂移侵蚀越快，重训越频繁
# 10d/7天、20d/14天、40d/30天；40d 训练最重（10年671万样本）间隔最长
ACTIVE_MODELS = [
    ('lgb_reg_10d_v3.txt',            '10d v3',        7),
    ('lgb_reg_20d_mac_v1.txt',        '20d mac_v1',   14),
    ('lgb_reg_40d_new_stkfactor.txt', '40d new_stkfactor', 30),
    ('lgb_reg_etf_20d_v1.txt',        'ETF 20d v1',   30),
]
MAX_AGE_URGENT = 60

IC_MEAN_MIN = {  # (列名, 显示名, 阈值)——IC 哨兵：近 6 个信号日均值低于阈值 → 提前重训（不等日历到期）
    # 2026-08-07 用户拍板：可信 IC 仅 8/3 起 4 天（8/1 前评分管线失真作废），阈值先保守
    # （10d/20d<0.10、40d<0.15、融合<0.10），待 ic_window 真窗口积累 ~8 周（40d 最早 8/19）后校准
    'ic_fusion': ('融合IC', 0.10),
    'ic_reg40':  ('40d IC', 0.15),
    'ic_reg20':  ('20d IC', 0.10),
    'ic_reg10':  ('10d IC', 0.10),
}

now = datetime.now()
issues = []
infos = []

print("=" * 62)
print("模型重训提醒检查  %s" % now.strftime('%Y-%m-%d %H:%M'))
print("=" * 62)

# ---------- 1. 模型文件年龄 ----------
print("\n[1] 模型文件年龄（训练时间）")
for fname, label, max_age in ACTIVE_MODELS:
    p = BASE / 'models' / fname
    if not p.exists():
        issues.append(f"{label} ({fname}) 模型文件不存在！")
        print(f"  {label:18s} ❌ 文件缺失: {fname}")
        continue
    mtime = datetime.fromtimestamp(p.stat().st_mtime)
    age = (now - mtime).days
    mark = ""
    if age > MAX_AGE_URGENT:
        mark = " ⚠️ 建议立即重训"
        issues.append(f"{label} 模型已 {age} 天未重训（>{MAX_AGE_URGENT}天）")
    elif age > max_age:
        mark = " ⚠️ 考虑重训"
        issues.append(f"{label} 模型已 {age} 天未重训（>{max_age}天）")
    print(f"  {label:18s} {mtime:%Y-%m-%d}  距今 {age:3d} 天{mark}")

# ---------- 2. 模型级 IC ----------
print("\n[2] 模型级 IC（ic_daily，近 6 条）")
ic_rows = []
try:
    con = sqlite3.connect(str(STATE_DB))
    con.row_factory = sqlite3.Row
    cur = con.execute(
        "SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion "
        "FROM ic_daily ORDER BY signal_date DESC LIMIT 6")
    ic_rows = [dict(r) for r in cur.fetchall()]
    if ic_rows:
        for r in reversed(ic_rows):
            print("  %s  reg10=%+.3f reg20=%+.3f reg40=%+.3f fusion=%+.3f" % (
                r['signal_date'], r['ic_reg10'] or 0, r['ic_reg20'] or 0,
                r['ic_reg40'] or 0, r['ic_fusion'] or 0))
        if len(ic_rows) >= 3:
            for col, (label, thresh) in IC_MEAN_MIN.items():
                vals = [r[col] for r in ic_rows if r[col] is not None]
                if not vals:
                    continue
                mean = sum(vals) / len(vals)
                flag = " ⚠️ 走弱" if mean < thresh else ""
                if mean < thresh:
                    issues.append(f"{label} 近 {len(vals)} 日均值 {mean:+.3f} < {thresh}")
                print(f"  近 {len(vals)} 日 {label}均值: {mean:+.4f}{flag}")
        else:
            infos.append("ic_daily 数据不足 3 条，IC 趋势判断暂不可靠")
            print("  （ic_daily 数据不足 3 条，仅展示原始记录）")
    else:
        infos.append("ic_daily 无数据（模型级 IC 尚未采集）")
        print("  （无数据）")
except Exception as e:
    print("  读取 ic_daily 失败:", e)
    infos.append("ic_daily 读取失败: %s" % e)

# ---------- 3. 三因子融合滚动 IC ----------
print("\n[3] 三因子融合滚动 IC（factor_ic_roll, window=20）")
try:
    cur = con.execute(
        "SELECT as_of_date, mean_ic, win_rate, n_days FROM factor_ic_roll "
        "WHERE factor_name='fusion_3f_score' AND window=20 ORDER BY as_of_date DESC LIMIT 3")
    fr = cur.fetchall()
    if fr:
        for r in reversed(fr):
            print("  %s  mean_ic=%+.4f  win_rate=%.1f%%" % (
                r[0], r[1] or 0, (r[2] or 0) * 100))
        latest = fr[0]
        if (latest[1] or 0) < 0:
            issues.append("fusion_3f_score 最新滚动 IC 为负 (%.3f)" % (latest[1] or 0))
    else:
        infos.append("factor_ic_roll 无 fusion_3f_score 记录")
        print("  （无记录）")
except Exception as e:
    print("  读取 factor_ic_roll 失败:", e)
    infos.append("factor_ic_roll 读取失败: %s" % e)

con.close()

# ---------- 结论 ----------
print("\n" + "=" * 62)
if issues:
    print("结论: ⚠️ 需要关注重训 —— %d 项触发" % len(issues))
    for it in issues:
        print("  - " + it)
else:
    print("结论: ✅ 暂不需要重训（模型均较新，IC 未见明显走弱）")
for it in infos:
    print("  提示: " + it)
print("=" * 62)
sys.exit(0)
