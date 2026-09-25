#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送盘后合并报告全文到主QQ（09-15 对齐 M2 _cron_report 方案）。
cron agent 先 write_file 写 analysis/_postmarket_report.txt，再跑本脚本逐段独立send。
纪律：按行分块3800留200余量；每段独立send+重试；全部成功后才删临时文件；
send失败=硬失败必须补推到成功，不接受"回执sent但用户没收到"。"""
import subprocess, time, os

# 09-17 修复：cron 会话环境变量 HERMES_CRON_AUTO_DELIVER_* 会被继承进子进程，
# 触发 send_message_tool 的"cron自动投递同目标去重"逻辑把 hermes send 全部 Skipped（假成功/零送达）。
# 本脚本是显式分条推送，与自动投递的"整段最终回复"是两条不同内容，必须免疫该环境。
for _k in ("HERMES_CRON_AUTO_DELIVER_PLATFORM", "HERMES_CRON_AUTO_DELIVER_CHAT_ID", "HERMES_CRON_AUTO_DELIVER_THREAD_ID"):
    os.environ.pop(_k, None)

SRC = os.path.expanduser("~/.hermes/stockdb/analysis/_postmarket_report.txt")
DEST = "qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616"

if not os.path.exists(SRC):
    print(f"报告文件不存在: {SRC}")
    raise SystemExit(1)

with open(SRC, "r", encoding="utf-8") as f:
    text = f.read().strip()

if len(text) < 200:
    print(f"报告内容过短({len(text)}字)，疑似生成失败，不推送")
    raise SystemExit(1)

# ---- 发布前硬校验（09-23 实锤补上：09-21 旧稿被当 09-22 推送，+1.43% 假数零拦截）----
# 校验1: 报告标题日期必须是今天或昨天（盘后报告写当日或前一交易日）
# 校验2: 报告若写了"中证1000 ±x%"，x 必须命中 index_daily_raw 最近5交易日之一
import datetime as _dt, re as _re
try:
    import duckdb as _duck
    _today = _dt.date.today()
    _m = _re.search(r"盘后综合报告\s*(\d{4})-(\d{2})-(\d{2})", text)
    if _m:
        _d = _dt.date(int(_m.group(1)), int(_m.group(2)), int(_m.group(3)))
        if not ((_today - _d).days <= 1):
            print(f"发布前校验失败: 报告标题日期 {_d} 距今 {(_today-_d).days} 天，疑似陈旧稿件，拒绝推送")
            raise SystemExit(1)
    _c = _duck.connect(os.path.expanduser("~/.hermes/stockdb/tushare.db"), read_only=True)
    _recent = {round(r[0], 2) for r in _c.execute(
        "SELECT pct_chg FROM index_daily_raw WHERE ts_code='000852.SH' ORDER BY trade_date DESC LIMIT 5").fetchall()}
    _c.close()
    for _pm in _re.finditer(r"中证1000[^0-9+\-]{0,12}([+-]?\d+\.\d+)%", text):
        _v = round(float(_pm.group(1)), 2)
        if _v not in _recent:
            print(f"发布前校验失败: 报告写中证1000 {_v}%，不在权威库近5日 {sorted(_recent)} 内，拒绝推送")
            raise SystemExit(1)
    print("发布前校验: 通过（标题日期+中证1000涨跌幅对拍）")
except SystemExit:
    raise
except Exception as _e:
    print(f"发布前校验异常({type(_e).__name__}: {_e})——放行但告警")

# 按行分块，每块<=3800
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
            capture_output=True, text=True, timeout=90)
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
    _dst = os.path.join(_ARCDIR, "postmarket_" + datetime.datetime.now().strftime("%Y%m%d") + ".txt")
    shutil.copyfile(SRC, _dst)
    print(f"已归档: {_dst}")
except Exception as _e:
    print(f"归档失败(不影响推送): {type(_e).__name__}: {_e}")
os.remove(SRC)
