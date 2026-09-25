# -*- coding: utf-8 -*-
# 追加 2026-09-16(夜)/00:4x 两条自主决策到 DECISIONS.md
row1 = "| 2026-09-16 | 运维 | 盘后推送脚本 _cron_push_report.py 开头剥除 HERMES_CRON_AUTO_DELIVER_* 三个环境变量 | 今晚 23:55 实锤：cron 子进程继承这三个变量后 send_message_tool._maybe_skip_cron_duplicate_send 判定\"与自动投递同目标\"，5段×3次重试全部 Skipped（零送达，脚本按 stderr 判失败硬失败才没造成假成功）；与 08:05 盘前故障同 bug 类。09-15 核查曾判\"未发生\"是因为当时网关进程环境未带该组变量，09-16 网关重启(DECISIONS 13:20 行)后开始生效 | 删掉脚本开头 for _k in (...) os.environ.pop 五行即回滚 |\n"
row2 = "| 2026-09-16 | 运维 | 盘后报告全文归档 analysis/archive/postmarket_20260917.txt 上线首跑生效 | 昨日报告无法复盘的缺口修复（推送脚本删源文件前 copyfile），今晚起【我的判断】逐日打分闭环恢复 | 归档为纯新增文件，无回滚需求 |\n"

p = "/Users/zantao/.hermes/stockdb/DECISIONS.md"
with open(p, "a", encoding="utf-8") as f:
    f.write(row1 + row2)
print("appended 2 rows")
