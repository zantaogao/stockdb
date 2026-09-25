#!/usr/bin/env python3
"""给盘中/盘前/盘后/巡逻类 cron 任务的 prompt 头部加交易日历硬闸。
2026-09-25 调休休市误交易事故：脚本级闸已补（exec/decision/snapshot/adjust/backfill），
但报告类任务是 agent-prompt 驱动（不跑被闸脚本），休市日照常烧 token 出报告。
本脚本给这些任务的 prompt 加一行：先跑日历检查脚本，=0 → 只回「今日休市，无报告」。
幂等：已含「交易日历硬闸」的 prompt 跳过。备份 jobs.json.bak.20260925_calgate（如不存在才建）。
"""
import json, shutil
from pathlib import Path

P = Path('/Users/zantao/.hermes/cron/jobs.json')
BAK = Path('/Users/zantao/.hermes/cron/jobs.json.bak.20260925_calgate')
CHECK = '/usr/bin/python3 -B /Users/zantao/.hermes/stockdb/scripts/_cron_tradecal_check.py'
GATE = (
    "⚠️交易日历硬闸（2026-09-25 调休休市误交易事故）：先跑 " + CHECK +
    "（输出 TRADING_DAY=1 或 0）。=0（节假日/周末休市）→ 最终回复只写一行「今日休市，无报告」，"
    "禁止数据采集、禁止写任何文件、禁止推QQ。=1 才继续。\n"
)

def main():
    if not BAK.exists():
        shutil.copy(P, BAK)
        print(f'备份 → {BAK}')
    data = json.loads(P.read_text())
    changed = []
    for j in data['jobs']:
        pr = j.get('prompt') or ''
        if not pr or '交易日历硬闸' in pr:
            continue
        hit = any(k in pr for k in ('盘中分析师', '盘前报告分析师', '交易员，全权裁决', 'A-Quant 夜间巡逻'))
        if '每周统计复盘' in pr:
            hit = False  # 周日跑，不需要
        if hit:
            j['prompt'] = GATE + pr
            changed.append((j['id'][:12], j.get('name', '')))
    if not changed:
        print('无任务需要加闸（可能已加过）')
        return
    tmp = P.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(P)
    print(f'加闸 {len(changed)} 个任务:')
    for c in changed:
        print('  ', c[0], c[1])

if __name__ == '__main__':
    main()
