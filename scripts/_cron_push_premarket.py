#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送盘前报告全文到主QQ（09-15 对齐 M2 _cron_report 方案）。
cron agent 先 write_file 写 analysis/_premarket_report.txt，再跑本脚本逐段独立send。
纪律：按行分块3800留200余量；每段独立send+重试；全部成功后才删临时文件。"""
import subprocess, time, os

SRC = os.path.expanduser("~/.hermes/stockdb/analysis/_premarket_report.txt")
DEST = "qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616"

# 09-15 修复：cron 会话内 `hermes send` 到"本任务自动投递目标"会被
# _maybe_skip_cron_duplicate_send 静默跳过（success=true + skipped=true，stdout 无 "sent"），
# 导致盘前报告推不出去。剥掉 HERMES_CRON_AUTO_DELIVER_* 后按普通发送执行。
_SEND_ENV = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_CRON_AUTO_DELIVER_")}


if not os.path.exists(SRC):
    print(f"报告文件不存在: {SRC}")
    raise SystemExit(1)

with open(SRC, "r", encoding="utf-8") as f:
    text = f.read().strip()

if len(text) < 200:
    print(f"报告内容过短({len(text)}字)，疑似生成失败，不推送")
    raise SystemExit(1)

chunks, cur = [], ""
for line in text.split("\n"):
    if len(cur) + len(line) + 1 > 3800 and cur:
        chunks.append(cur)
        cur = line
    else:
        cur = cur + "\n" + line if cur else line
if cur:
    chunks.append(cur)

failed = []
for i, c in enumerate(chunks, 1):
    content = c if len(chunks) == 1 else f"[{i}/{len(chunks)}]\n{c}"
    ok = False
    for attempt in range(3):
        r = subprocess.run(
            ["hermes", "send", "-t", DEST, content],
            capture_output=True, text=True, timeout=90, env=_SEND_ENV)
        if r.returncode == 0 and "sent" in (r.stdout or "").lower():
            print(f"段{i}/{len(chunks)} ({len(content)}字) ok")
            ok = True
            break
        print(f"段{i} 第{attempt+1}次失败: {(r.stderr or r.stdout or '').strip()[:120]}")
        time.sleep(8)
    if not ok:
        failed.append(i)
    time.sleep(2)

if failed:
    print(f"有失败段: {failed}，临时文件保留待重推: {SRC}")
    raise SystemExit(1)

print(f"推送完成: {len(text)}字/{len(chunks)}段")
# 2026-09-16 归档修复：源文件删除前留档，否则报告全文（含【我的判断】）次日无法复盘
try:
    import datetime, shutil
    _ARCDIR = os.path.expanduser("~/.hermes/stockdb/analysis/archive")
    os.makedirs(_ARCDIR, exist_ok=True)
    _dst = os.path.join(_ARCDIR, "premarket_" + datetime.datetime.now().strftime("%Y%m%d") + ".txt")
    shutil.copyfile(SRC, _dst)
    print(f"已归档: {_dst}")
except Exception as _e:
    print(f"归档失败(不影响推送): {type(_e).__name__}: {_e}")
os.remove(SRC)
