#!/usr/bin/env python3
"""推送 IC 全面审查结果到 QQ 2026-08-08"""
import subprocess, sys

QQ_TARGET = 'qqbot:2D719CDE220EEDA98203CE4E41B2141D'

msg = """📋 IC 页面全面审查完成（08-08）

1️⃣ stk_factor 08-07 双份事故（11068 行）
根因: 8/7 23:06 遗留进程与手动补拉并发, 共享 tushare.db.new 路径互相踩踏
✅ 已清理(11068→5534) + backfill 改原子交换版 + 健康检查加行数告警(>daily×1.1+500 报警)

2️⃣ IC 页面 8 模块独立复算结论:
✅ model_ic (ic_daily 8/3-8/6): 4 行 fusion/reg10/20/40 复算全部一致
✅ cmmr_ic/fusion_ic: 7/28-7/31 失真期已删
   (7/30 信号复制日实锤: 与 7/29 三模型分 100% 相同)
   剩 8/3-8/6 可信 4 行
✅ fusion_roll: 7/24/27/29 旧 bug 行已删(浮点匹配漏股)
   剩 7/30 起 6 天干净
✅ etf_ic: ic_20d 实现 bug 已修(原取次日=恒等 spearman,
   改第20交易日)+重复行/7/22/7/24 未来泄漏行已清
✅ 面板 fusion 行 icir/max/min 不再显示假 0

3️⃣ 当前状态（全部 8/3 起可信口径）:
model_ic: fusion IC 0.34 (4天) | reg10 0.34 reg20 0.34 reg40 0.26
cmmr_roll: cmmr +0.107 全正(4天) | CMMR+ +0.33
fusion_roll: 三因子 -0.168 | 强买 +0.040
etf_ic 最新: 8/6 pearson 0.216 spearman 0.286 (1814只 98%覆盖)
window_ic: 空(8/17 起真窗口积累)

系统监控数据现已干净可信。备份: state.db.bak.20260808_ic_clean / tushare.db.bak.20260808_dup"""

r = subprocess.run(['hermes', 'send', '-t', QQ_TARGET, msg],
                   capture_output=True, timeout=60)
if r.returncode == 0:
    print('✅ QQ 推送成功')
else:
    print(f'❌ 推送失败: {r.stderr.decode()[:300]}')
    sys.exit(1)
