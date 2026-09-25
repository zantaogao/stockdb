#!/bin/bash
# 09-07改: 全部输出重定向到 logs/update_api_*.log，cron stdout 只回显尾部摘要。
# 原因: cron 采集层分块解码 stdout 会在多字节汉字中间截断(0xef/0xbe)，
#       把成功的更新误报成失败(09-07事故: 库已写好但采集层崩→看门狗杀进程→交换没走)。
cd /Users/zantao/.hermes/stockdb || exit 1
LOG="logs/update_api_$(date +%Y%m%d_%H%M%S).log"
/usr/bin/python3 -B scripts/update_tushare_api.py > "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "UPDATE_FAIL exit=$RC log=$LOG"
  tail -15 "$LOG" | tr -cd '\11\12\15\40-\176'   # 去多字节，防采集层再截断
  exit $RC
fi
echo "UPDATE_OK log=$LOG"
tail -5 "$LOG" | tr -cd '\11\12\15\40-\176'