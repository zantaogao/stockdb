#!/usr/bin/env python3
"""体检：哪些 cron 任务今天（2026-09-25 休市日）实际跑了，各自有没有日历闸。
脚本型(no_agent)任务 → 查其 .sh/脚本链里有无日历检查（排除 jobs.json 的 prompt 闸）。"""
import json, subprocess, sys
from pathlib import Path

jobs = json.loads(Path('/Users/zantao/.hermes/cron/jobs.json').read_text())['jobs']
today = '2026-09-25'

rows = []
for j in jobs:
    if not j.get('enabled'):
        continue
    last = j.get('last_run_at') or ''
    if not last.startswith(today):
        continue
    name = j.get('name', '')
    script = j.get('script')
    has_prompt_gate = '交易日历硬闸' in (j.get('prompt') or '')
    # 脚本型：在 stockdb/scripts、hermes/scripts、scripts/ 找脚本，链式 grep trade_calendar
    script_gate = False
    if script:
        for d in ['/Users/zantao/.hermes/stockdb/scripts', '/Users/zantao/.hermes/scripts', '/Users/zantao/.hermes/stockdb']:
            p = Path(d) / script
            if p.exists():
                try:
                    txt = p.read_text(errors='ignore')
                except Exception:
                    txt = ''
                # 简单判定：自身含 trade_calendar 或调用链里某脚本名含 gate（递归太深先只查本层）
                if 'trade_calendar' in txt or 'TRADING_DAY' in txt:
                    script_gate = True
                else:
                    # 一层链：脚本里调用的其它 .py/.sh，查其名
                    import re
                    called = re.findall(r'[\w/\-]+\.(?:py|sh)\b', txt)
                    for c in called:
                        cp = Path(c) if c.startswith('/') else None
                        for dd in ['/Users/zantao/.hermes/stockdb/scripts', '/Users/zantao/.hermes/scripts']:
                            cand = Path(dd) / Path(c).name
                            if cand.exists():
                                try:
                                    ctxt = cand.read_text(errors='ignore')
                                except Exception:
                                    ctxt = ''
                                if 'trade_calendar' in ctxt:
                                    script_gate = True
                                    break
                        if script_gate:
                            break
                break
    rows.append((j['id'][:12], name, j.get('schedule', {}).get('expr', ''), '有prompt闸' if has_prompt_gate else '', '有脚本闸' if script_gate else '⚠️无闸' if script and not has_prompt_gate else ''))

print(f'今天跑过的任务: {len(rows)}')
for r in sorted(rows, key=lambda x: x[0]):
    print(' | '.join(str(x) for x in r))
