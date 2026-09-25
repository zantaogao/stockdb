#!/usr/bin/env python3
# 排查 report_pdf.py 模块级变量污染：BaseDocTemplate 拿到字符串 topMargin
import sys
src = open("/Users/zantao/.hermes/stockdb/scripts/report_pdf.py").read().splitlines()
code = "\n".join(src[:142])  # def build 之前
g = {"__name__": "__notmain__"}
try:
    exec(compile(code, "report_pdf_head", "exec"), g)
except SystemExit:
    pass
except Exception as e:
    print("头部执行异常:", type(e).__name__, e)
for k in ("L", "Rm", "LM", "RM", "CW", "mm", "A4", "W", "H"):
    print(k, "=", repr(g.get(k, "<absent>"))[:80])
