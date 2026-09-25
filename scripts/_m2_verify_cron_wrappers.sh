#!/bin/bash
# M2 cron wrapper 批量验证（2026-08-23）— 模拟 cron PATH 环境
# 排除: 推送类(daily_report/push_top10/monitor_qqbot2)、长任务(update_tushare_api/update_etf/tdx_sync/backfill_stk_factor/nas_backup)、已pause(check_qwen38/mean_reversion)
export PATH="$HOME/.hermes/hermes-agent/venv/bin:$PATH"
cd ~/.hermes/stockdb || exit 1
PASS=0; FAIL=0; SKIP=0
for sh in ic_daily backtest_cmmr backtest_fusion backtest_weekly_report cmmr_ic_daily etf_scoring fusion_3f_daily fusion_center_daily health_check monitor_40d_w40 remind_retrain sync_watchlist weekly_health_check check_and_alert signal_agent intraday_decision exec_agent strategy_accounts_daily fusion_3f_intraday; do
  f=~/.hermes/scripts/${sh}.sh
  [ -f "$f" ] || { echo "[缺失] $sh"; FAIL=$((FAIL+1)); continue; }
  OUT=$(timeout 300 bash "$f" 2>&1)
  RC=$?
  if [ $RC -eq 0 ]; then
    # 判断是否有实际输出（真跑 vs 静默跳过）
    if echo "$OUT" | grep -qiE "error|Traceback|ModuleNotFound|No such file|not found|failed" && ! echo "$OUT" | grep -qiE "预期|PASS|跳过|非交易时段|无操作"; then
      echo "[⚠️ 输出含错误] $sh (rc=0)"; echo "$OUT" | grep -iE "error|Traceback|ModuleNotFound|No such" | head -3; FAIL=$((FAIL+1))
    else
      echo "[✅] $sh"; PASS=$((PASS+1))
    fi
  else
    echo "[❌ rc=$RC] $sh"; echo "$OUT" | tail -5; FAIL=$((FAIL+1))
  fi
done
echo "======================"
echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
