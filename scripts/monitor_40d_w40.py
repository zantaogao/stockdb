#!/usr/bin/env python3
"""
40d 真窗口（w40）监控 — 2026-08-07 用户拍板"保持旧模型，真窗口验证"
=============================================================
⚠️ 2026-08-10 修正预期：ic_window 可信基线 = 8/3 起信号日（8/8 已删失真期 7/23-7/31，
sig_dates 强制 >= 20260803）。8/3 + 40 交易日 ≈ 9/29 前后，w40 第一条实际 9 月底回填
（w10 系列 8/17 先回填，w40 全量列待 9 月底）；"8/19"是旧计划（基于已删除的 7/24 失真行）。
阶段 1：每天检查 ic_window 的 ic_reg40_w40 积累（9 月底起第一条回填）
  - 无 w40 数据：静默（不打扰）
  - 开始积累（第一条）：通知"w40 开始回填"
  - 积累中：静默
  - ≥10 条：输出旧模型 w40 IC 表现 + 提示跑增量对比（阶段 2）

阶段 2：w40 ≥10 条后（约 10 月中旬，第 10 个可信信号日 8/12 的 w40 ≈ 10/9），
  用 scripts/compare_40d_w40_inc.py
  对同批信号日重算增量 v2 的 40 日窗口 IC，对比 ic_reg40_w40（旧模型）。
"""
import sqlite3, sys, subprocess
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'signals.db'  # v2温层
THRESHOLD = 10  # w40 达到多少条出正式结论
QQ_TARGET = 'qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616'  # 主 bot（同盘后报告）


def push(text):
    """推送到 QQ（hermes send，同 daily_report.py 方式）；失败不阻断"""
    try:
        subprocess.run(['hermes', 'send', '-t', QQ_TARGET, text], timeout=30)
    except Exception as e:
        print(f'推送失败: {e}')


def main():
    conn = sqlite3.connect(str(STATE_DB))
    rows = conn.execute("""
        SELECT signal_date, ic_reg40_w40, ic_fusion_w40 FROM ic_window
        WHERE ic_reg40_w40 IS NOT NULL ORDER BY signal_date
    """).fetchall()
    conn.close()

    if not rows:
        # w40 尚未开始：静默（no_agent 空输出不打扰）
        return

    n = len(rows)
    latest = rows[-1][0]
    ics = [r[1] for r in rows]
    mean_ic = sum(ics) / n
    pos = sum(1 for x in ics if x > 0)

    if n == 1:
        # 第一条回填：通知开始积累
        msg = (f"📊 40d 真窗口（w40）开始回填: 第一条 signal_date={latest}, IC={ics[0]:+.4f}\n"
               "按计划每交易日积累一条，约 10 条（10 月中旬）后对比旧模型 vs 增量 v2")
        print(msg)
        push(msg)
        return

    if n < THRESHOLD:
        # 积累中：静默（避免每天打扰）
        return

    # ≥10 条：正式结论 + 提示增量对比
    print(f"📊 40d 真窗口（w40）已积累 {n} 条（signal_date {rows[0][0]}~{latest}）")
    print(f"旧模型 w40 IC: 均值={mean_ic:+.4f} 正天数={pos}/{n} 最新={ics[-1]:+.4f}")
    if mean_ic < 0.10:
        msg = (f"📊 40d 真窗口（w40）已积累 {n} 条\n"
               f"旧模型 w40 IC 均值 {mean_ic:+.4f} < 0.10（正天数 {pos}/{n}）—— 40d 基础可能退化，"
               f"建议跑增量对比:\n  python3 -B scripts/compare_40d_w40_inc.py")
        print(msg)
        push(msg)
    else:
        msg = (f"📊 40d 真窗口（w40）已积累 {n} 条\n"
               f"旧模型 w40 IC 均值 {mean_ic:+.4f} ≥ 0.10（正天数 {pos}/{n}）—— 基础仍有效，继续观察")
        print(msg)
        push(msg)


if __name__ == '__main__':
    main()
