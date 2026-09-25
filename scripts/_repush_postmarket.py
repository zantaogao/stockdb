#!/usr/bin/env python3
"""一次性：09-14盘后报告全文，显式3500字分片+序号重推主QQ（QQ对连发长文有速率限制，逐条独立发最稳）。"""
import subprocess, sys, time
from pathlib import Path

SRC = Path('/Users/zantao/.hermes/stockdb/analysis/_repush_postmarket.txt')
TARGET = 'qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616'
CHUNK = 3500

text = SRC.read_text(encoding='utf-8').strip()
chunks, cur = [], ''
for line in text.split('\n'):
    if len(cur) + len(line) + 1 > CHUNK and cur:
        chunks.append(cur); cur = line
    else:
        cur = cur + '\n' + line if cur else line
if cur: chunks.append(cur)

ok = fail = 0
for i, c in enumerate(chunks, 1):
    msg = f'【09-14盘后报告 片{i}/{len(chunks)}】\n' + c
    for attempt in (1, 2, 3):
        r = subprocess.run(['hermes', 'send', '-t', TARGET, msg],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            print(f'✅ 片{i}/{len(chunks)} ({len(msg)}字)'); ok += 1; break
        time.sleep(3)
    else:
        print(f'❌ 片{i}: {(r.stderr or r.stdout)[:150]}'); fail += 1
    time.sleep(1.5)
print(f'完成: {ok}成/{fail}败')
sys.exit(0 if fail == 0 else 2)
