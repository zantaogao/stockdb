#!/usr/bin/env python3
"""一次性：把最新夜间简报压缩成两条推主QQ。跑完可留档复用。"""
import json, subprocess, time, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
u = json.load(open(BASE / 'analysis/opinion_universe.json'))
d, ex = u['signal_date'], u['exec_date']
TARGET = 'qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616'

lines = [f"📋 周五晚名单简报（信号日{d}→执行日{ex}）", ""]
rb = u['accounts']
due = [v['name'] for v in rb.values() if v['rebalance']['due']]
near = [f"{v['name']}(剩{v['rebalance']['days_left']}日)" for v in rb.values()
        if not v['rebalance']['due'] and v['rebalance']['days_left'] <= 3]
lines.append("🗓 调仓: " + ("、".join(due) if due else "今无") +
             ("；临近 " + "、".join(near) if near else ""))
lines.append("")
lines.append("【五份名单·今日买入候选】")
bylist = {}
for code, v in u['universe'].items():
    for l in v['in_lists']:
        bylist.setdefault(l['account'], []).append((code, v['name'], l['score'], v))
order = ['三因子融合', 'CMMR独立', 'CMMR+融合', '中枢版Top10', '中枢版+三模型']
for name in order:
    items = sorted(bylist.get(name, []), key=lambda x: -x[2])
    lines.append(f"◆ {name}:")
    for code, nm, sc, v in items:
        chg = v.get('chg5')
        star = '⭐' if len(v['in_lists']) >= 2 else ''
        hot = '⚡' if chg is not None and chg >= 15 else ''
        chgs = f"{chg:+.1f}%" if chg is not None else '?'
        lines.append(f" {code}{nm} {sc:g} 5日{chgs}{hot}{star}")
    lines.append("")
m1 = "\n".join(lines)

hold = []
for code, v in u['universe'].items():
    for h in v['holds']:
        hold.append((h['account'], code, v['name'], h['avg_cost'], h['stop_loss']))
n_main = sum(1 for v in u['universe'].values()
             if any(x['account'] == '主账户' for x in v['holds']))
m2_lines = [f"【持仓观察】主账户{n_main}只 + 策略账户共{len(hold)}笔"]
warn = []
for acc, code, nm, cost, sl in hold:
    if cost and sl and cost / sl > 0.97:
        warn.append((acc == '主账户', cost / sl, f" {'🔴' if acc=='主账户' else '⚠️'}{acc} {code}{nm} 本{cost} 损{sl}"))
for is_main, ratio, s in sorted(warn, key=lambda x: -x[1]):
    m2_lines.append(s)
m2_lines.append("")
m2_lines.append("⭐=多榜共振 ⚡=5日涨幅超15%。盘中每10分钟自动盯盘：进买入区/追高/破止损推QQ，面板「盘中意见」页留档。")
m2 = "\n".join(m2_lines)

for tag, m in (('brief', m1), ('holds', m2)):
    r = subprocess.run(['hermes', 'send', '-t', TARGET, m],
                       capture_output=True, text=True, timeout=60)
    print(tag, 'rc=', r.returncode, 'len=', len(m), (r.stdout or r.stderr or '').strip()[:120])
    time.sleep(0.5)