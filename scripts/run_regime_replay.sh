#!/bin/bash
# 回放作业独立启动器（09-13 v2）：由 nohup 脱链启动，与任何 Hermes CLI / 终端会话无关。
# 幂等断点续跑：已完成的交易日会跳过。
# 收尾：无论正常跑完还是异常退出，都把 mlx-serve 拉回来（用户要求「跑完再拉起来」）。
set -u
cd /Users/zantao/.hermes/stockdb || exit 1
MLX_LABEL=com.mlxserve.flash.server
MLX_PLIST="$HOME/Library/LaunchAgents/$MLX_LABEL.plist"
MLX_BIN=/Users/zantao/bin/mlx-serve-26.9.2/mlx-serve
MLX_MODEL=/Users/zantao/models/Qwen3.8-Flash-Next-Uncensored-MLX-Serve-4bit

echo "=== regime_replay start $(date '+%F %T') wrapper_pid=$$ ==="
echo "range ${START:-20220104} .. ${END:-20260911}"

/usr/bin/nice /usr/bin/python3 -B scripts/regime_replay_2022.py "${START:-20220104}" "${END:-20260911}" &
CHILD=$!
trap 'echo "[wrapper] signal -> stopping replay pid $CHILD"; kill -TERM $CHILD 2>/dev/null' TERM INT

wait $CHILD
RC=$?
echo "=== replay exited rc=$RC at $(date '+%F %T') ==="

# ---- 收尾：把 mlx-serve 拉回来（三级兜底）----
if launchctl print gui/$(id -u)/$MLX_LABEL >/dev/null 2>&1; then
  echo "[wrapper] mlx-serve 已在跑，跳过回拉"
else
  if launchctl bootstrap gui/$(id -u) "$MLX_PLIST" >/dev/null 2>&1; then
    echo "[wrapper] mlx-serve 已回拉 (launchd bootstrap)"
  elif launchctl load -w "$MLX_PLIST" >/dev/null 2>&1; then
    echo "[wrapper] mlx-serve 已回拉 (launchctl load -w)"
  else
    echo "[wrapper] launchd 两条路都失败，直接后台拉起 mlx-serve（无 KeepAlive 守护）"
    nohup "$MLX_BIN" --model "$MLX_MODEL" --serve --port 11234 --mtp \
      --prefix-cache-mem 8GB --prefix-cache-disk 32GB \
      >> /Users/zantao/.hermes/logs/mlx_manual_restart.log 2>&1 &
    echo "[wrapper] mlx-serve 已直接拉起 pid=$!"
  fi
fi
echo "=== wrapper done $(date '+%F %T') ==="
exit $RC
