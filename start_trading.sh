#!/bin/bash
# 启动模拟交易系统 + Cloudflare隧道（外网访问）
# 用法: bash start_trading.sh

PORT=8081
PASS="${SIM_PASSWORD:-stock888}"

echo "📊 启动模拟交易系统..."

# 启动 simulate.py
cd ~/.hermes/stockdb
SIM_PASSWORD="$PASS" python3 simulate.py --port $PORT &
SIM_PID=$!
echo "  模拟交易系统 PID: $SIM_PID (端口 $PORT)"

# 等待启动
sleep 2

# 启动 cloudflare 隧道
echo "🌐 启动 Cloudflare 隧道..."
cloudflared tunnel --url http://localhost:$PORT > /tmp/cloudflared.log 2>&1 &
CF_PID=$!
echo "  Cloudflare PID: $CF_PID"

# 等待隧道建立，提取URL
echo "  等待隧道建立..."
for i in $(seq 1 15); do
    URL=$(grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' /tmp/cloudflared.log 2>/dev/null | head -1)
    if [ -n "$URL" ]; then
        echo ""
        echo "═══════════════════════════════════════"
        echo "  ✅ 外网访问地址: $URL"
        echo "  密码: $PASS"
        echo "═══════════════════════════════════════"
        echo ""
        break
    fi
    sleep 1
done

if [ -z "$URL" ]; then
    echo "⚠️ 隧道URL获取超时，请检查 /tmp/cloudflared.log"
fi

echo "按 Ctrl+C 停止所有服务"
wait
