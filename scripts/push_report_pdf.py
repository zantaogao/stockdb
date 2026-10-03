#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告 txt → 版式 PDF → 推主QQ（09-23 用户拍板：盘后/盘前报告固定 PDF 版式；
10-02 月报接入同版式）。
用法: push_report_pdf.py <postmarket|premarket|monthly> [报告txt]
默认 postmarket → analysis/_postmarket_report.txt → Desktop/盘后综合报告_YYYY-MM-DD.pdf
monthly → analysis/_monthly_report.txt → Desktop/A-Quant月报_YYYY-MM.pdf（月份取txt首行）
成功输出 PDF_PUSHED 并归档 PDF 到 analysis/archive/；源 txt 保留不删。"""
import os, re, subprocess, sys, shutil
from datetime import datetime

MODE = sys.argv[1] if len(sys.argv) > 1 else "postmarket"
HOME = os.path.expanduser("~")
SC = f"{HOME}/.hermes/stockdb/scripts"

if MODE == "postmarket":
    src = sys.argv[2] if len(sys.argv) > 2 else f"{HOME}/.hermes/stockdb/analysis/_postmarket_report.txt"
    pdf = f"{HOME}/Desktop/盘后综合报告_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    title_sub = ""  # 默认取 txt 第2行
elif MODE == "monthly":
    src = sys.argv[2] if len(sys.argv) > 2 else f"{HOME}/.hermes/stockdb/analysis/_monthly_report.txt"
    _m = re.search(r"\d{4}-\d{2}", open(src, encoding="utf-8").read(200))
    _mon = _m.group(0) if _m else datetime.now().strftime("%Y-%m")
    pdf = f"{HOME}/Desktop/A-Quant月报_{_mon}.pdf"
    title_sub = ""
else:
    src = sys.argv[2] if len(sys.argv) > 2 else f"{HOME}/.hermes/stockdb/analysis/_premarket_report.txt"
    pdf = f"{HOME}/Desktop/盘前报告_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    title_sub = ""  # 默认取 txt 第2行

if not os.path.exists(src):
    print(f"报告文件不存在: {src}"); raise SystemExit(1)
_txt = open(src, encoding="utf-8").read()
if len(_txt.strip()) < 200:
    print("报告内容过短(<200字)，疑似生成失败，不推送"); raise SystemExit(1)

if not title_sub:
    _lines = _txt.splitlines()
    if len(_lines) > 1 and len(_lines[1].strip()) < 60:
        title_sub = _lines[1].strip()
r = subprocess.run(["/usr/bin/python3", "-B", f"{SC}/report_pdf.py", src, pdf, title_sub],
                   capture_output=True, text=True)
if r.returncode != 0 or not os.path.exists(pdf):
    print(f"PDF 排版失败: {r.stdout[-300:]} {r.stderr[-500:]}"); raise SystemExit(1)

r = subprocess.run(["/usr/bin/python3", "-B", f"{SC}/qq_pdf_send.py", pdf],
                   capture_output=True, text=True)
if r.returncode != 0 or "PDF 发送: ok" not in r.stdout:
    print(f"PDF 推送失败: {r.stdout[-300:]} {r.stderr[-300:]}"); raise SystemExit(1)

arcd = f"{HOME}/.hermes/stockdb/analysis/archive"
os.makedirs(arcd, exist_ok=True)
shutil.copyfile(pdf, os.path.join(arcd, os.path.basename(pdf)))
print(f"PDF_PUSHED {pdf}")
print(r.stdout.strip())
