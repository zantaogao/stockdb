"""全链路巡检: 找出所有硬编码融合权重/旧模型名/旧fusion公式的调用方, 确认v8全面替换"""
import subprocess, re, os

BASE = os.path.expanduser('~/.hermes/stockdb')

# 1. 硬编码旧融合公式: 0.375/0.625(0927上午v7), 0.20/0.30/0.50(0803旧), 0.25*reg10(新v8应唯一)
patterns = {
    '旧融合0.375_0.625': r'0\.375\*reg20|reg20_pred\s*\*\s*0\.375|0\.625\*reg40|reg40_pred\s*\*\s*0\.625',
    '更旧融合0.20_0.30_0.50': r'reg10_pred\s*\*\s*0\.20|reg20_pred\s*\*\s*0\.30|reg40_pred\s*\*\s*0\.50',
    'v8新融合0.25_0.75': r'reg10_pred\s*\*\s*0\.25|0\.25\*reg10',
}
for label, pat in patterns.items():
    print(f'--- {label} ---')
    out = subprocess.run(
        f"cd {BASE} && grep -rn -E '{pat}' --include=*.py --include=*.sh core/ scripts/ agents/ web/ ~/.hermes/scripts/ 2>/dev/null | grep -v -E '_cron_|analysis/|replay/|\\.bak|retired|backtest|_backtest|diag_|compare_|verify_|screen_|retrain_' | head -15",
        shell=True, capture_output=True, text=True).stdout
    print(out if out.strip() else '(无)')

# 2. 模型路径硬编码引用
print('--- 旧模型名引用(死引用排查) ---')
out = subprocess.run(
    f"cd {BASE} && grep -rn -E 'lgb_reg_10d_v[0-9]*\\.txt|lgb_reg_40d_new_stkfactor|lgb_reg_40d_v7|v10_v3_stats|v10_v5_stats|v40_v7_stats|v6_norm_stats' --include=*.py --include=*.sh core/ scripts/ agents/ web/ ~/.hermes/scripts/ 2>/dev/null | grep -v -E '_cron_|analysis/|replay/|\\.bak|retired|diag_|compare_|verify_|retrain_|_check_|_probe_|_verify|screen_|shadow_' | head -20",
    shell=True, capture_output=True, text=True).stdout
print(out if out.strip() else '(无)')

# 3. fusion重算/展示层: 前端/面板是否有独立fusion公式(web/, dashboard)
print('--- web/面板层fusion公式 ---')
out = subprocess.run(
    f"cd {BASE} && grep -rn -E 'fusion *=|fusion.*0\\.[0-9]+.*(reg|20|40)|reg.*0\\.[0-9]+.*\\+' --include=*.py --include=*.js web/ dashboard/ 2>/dev/null | grep -v -E '_cron_|test|analysis|replay' | head -15",
    shell=True, capture_output=True, text=True).stdout
print(out if out.strip() else '(无)')

# 4. 策略账户/执行端读融合的路径
print('--- 执行端读fusion路径 ---')
out = subprocess.run(
    f"cd {BASE} && grep -rn -E 'fusion_score|final_score' --include=*.py core/sim_engine.py agents/signal_agent.py scripts/intraday_decision.py scripts/strategy_accounts_daily.sh 2>/dev/null | grep -n -E 'read|SELECT|fusion' | head -10",
    shell=True, capture_output=True, text=True).stdout
print(out if out.strip() else '(无)')
