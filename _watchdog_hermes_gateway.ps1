# Hermes Gateway 守护脚本（2026-08-08 配置）
# 每 5 分钟由计划任务 HermesGatewayWatchdog 调用：
#   检测到 gateway 进程消失 → 用 schtasks /run 拉起 Hermes_Gateway → 写日志
$running = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*gateway*' -and ($_.Name -like 'python*')
}
if (-not $running) {
    $log = "C:\Users\zanta\hermes_gateway_watchdog.log"
    Add-Content $log ("{0} gateway down, restarting..." -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
    schtasks /run /tn "Hermes_Gateway" | Out-Null
    Start-Sleep 12
    $check = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like '*gateway*' -and ($_.Name -like 'python*')
    }
    if ($check) {
        Add-Content $log ("{0} restarted OK (PID {1})" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $check[0].ProcessId)
    } else {
        Add-Content $log ("{0} restart FAILED" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
    }
}
