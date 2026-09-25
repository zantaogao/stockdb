#!/bin/bash
# 交易系统全链路健康检查
# 运行时间: 工作日 9:30/11:30/14:30/15:30/18:30/20:30
# 静默模式：健康不输出，异常才报 + QQ推送

BASE="/Users/zantao/.hermes/stockdb"
LEDGER_DB="$BASE/ledger.db"     # v2热层账本
SIGNALS_DB="$BASE/signals.db"   # v2温层信号
TUSHARE_DB="$BASE/tushare.db"
ALERTS=""
WARNINGS=""

alert() {
    local module="$1"
    local msg="$2"
    ALERTS="$ALERTS
⚠️ [$module] $msg"
}

warn() {
    local module="$1"
    local msg="$2"
    WARNINGS="$WARNINGS
⚡ [$module] $msg"
}

today=$(date +%Y%m%d)
today_iso=$(date +%Y-%m-%d)
weekday=$(date +%u)  # 1=Mon..7=Sun
hour=$(date +%H)
minute=$(date +%M)
now_num=$((10#$hour * 100 + 10#$minute))

is_trading_time() {
    # 周二~周五 9:30-11:30, 13:00-15:00
    [ "$weekday" -ge 1 ] && [ "$weekday" -le 5 ] && \
    ( [ "$now_num" -ge 930 ] && [ "$now_num" -le 1130 ] ) || \
    ( [ "$now_num" -ge 1300 ] && [ "$now_num" -le 1500 ] )
}

is_weekday() {
    [ "$weekday" -ge 1 ] && [ "$weekday" -le 5 ]
}

# ═══════════════════════════════════════════════════════
# 1. DB 层 — 数据库完整性
# ═══════════════════════════════════════════════════════

# tushare.db DuckDB 魔数校验
if [ -f "$TUSHARE_DB" ]; then
    magic=$(dd if="$TUSHARE_DB" bs=1 skip=8 count=4 2>/dev/null | xxd -p)
    if [ "$magic" != "4455434b" ]; then
        alert "DB" "tushare.db 文件头异常 (magic=$magic)"
    fi
    size=$(stat -f%z "$TUSHARE_DB" 2>/dev/null)
    if [ "$size" -lt 1000000000 ]; then  # < 1GB 明显异常
        alert "DB" "tushare.db 体积异常: $((size/1048576))MB"
    fi
else
    alert "DB" "tushare.db 不存在"
fi

# ledger.db + signals.db SQLite 完整性（v2 三层，state.db 已冻结退役）
check_sqlite() {
    local db="$1" name="$2" min_size="${3:-1000000}"
    if [ -f "$db" ]; then
        integrity=$(python3 -c "
import sqlite3
try:
    c = sqlite3.connect('$db', timeout=5)
    r = c.execute('PRAGMA integrity_check').fetchone()[0]
    c.close()
    print(r)
except Exception as e:
    print('ERROR: ' + str(e)[:80])
" 2>/dev/null)
        if [ "$integrity" != "ok" ]; then
            alert "DB" "$name 完整性: $integrity"
        fi
        size=$(stat -f%z "$db" 2>/dev/null)
        if [ "$size" -lt "$min_size" ]; then  # 体积阈值按库类型
            alert "DB" "$name 体积异常: $((size/1024))KB"
        fi
    else
        alert "DB" "$name 不存在"
    fi
}
check_sqlite "$LEDGER_DB" "ledger.db" 10000    # 账本本是小库, <10KB 才算异常
check_sqlite "$SIGNALS_DB" "signals.db" 1000000  # 温层信号, <1MB 异常

# stale WAL 文件检查
for db in "$TUSHARE_DB" "$LEDGER_DB" "$SIGNALS_DB"; do
    wal="${db}.wal"
    shm="${db}.shm"
    for f in "$wal" "$shm"; do
        if [ -f "$f" ]; then
            age=$(( $(date +%s) - $(stat -f%m "$f") ))
            if [ "$age" -gt 86400 ]; then  # 超过24小时
                warn "DB" "$(basename $f) 残留 $(basename $db) ($((age/3600))小时前)"
            fi
        fi
    done
done

# ═══════════════════════════════════════════════════════
# 2. 数据链 — Tushare API 数据更新
# ═══════════════════════════════════════════════════════

out=$(python3 -c "
import duckdb, datetime

conn = duckdb.connect('$TUSHARE_DB', read_only=True)
today = '$today'
# daily 最新日期
latest = conn.execute('SELECT MAX(trade_date) FROM daily').fetchone()[0]
if latest is None:
    print('daily 表为空')
else:
    latest_str = str(latest)
    # 交易日判断：最新日期应该在 7 天内
    try:
        lt = datetime.datetime.strptime(latest_str, '%Y%m%d')
        delta = (datetime.datetime.now() - lt).days
        weekday = datetime.datetime.now().weekday()
        if delta > 10:
            print(f'daily 最新 {latest_str}, {delta} 天前 (可能数据未更新)')
    except: pass

# 各表行数基线检查
checks = {
    'daily': (5000000, 50000000),
    'daily_basic': (5000000, 50000000),
    'stk_limit': (10000000, 50000000),
    'money_flow': (5000000, 50000000),
    'adj_factor': (5000000, 20000000),
}
for tbl, (min_rows, max_rows) in checks.items():
    try:
        cnt = conn.execute(f'SELECT count(*) FROM {tbl}').fetchone()[0]
        if cnt < min_rows:
            print(f'{tbl} 行数过少: {cnt:,} (< {min_rows:,})')
        if cnt > max_rows:
            print(f'{tbl} 行数异常: {cnt:,} (> {max_rows:,})')
    except Exception as e:
        print(f'{tbl} 无法访问: {str(e)[:60]}')

# stock_basic 股票数
try:
    stocks = conn.execute('SELECT count(*) FROM stock_basic').fetchone()[0]
    if stocks < 4000:
        print(f'stock_basic 股票数异常: {stocks}')
except: pass
conn.close()
" 2>/dev/null)
while IFS= read -r line; do
    [ -n "$line" ] && alert "数据链" "$line"
done <<< "$out"


# ═══════════════════════════════════════════════════════
# 3. 评分链 — signal_history 评分系统
# ═══════════════════════════════════════════════════════

out=$(python3 -c "
import sqlite3, datetime
conn = sqlite3.connect('$STATE_DB', timeout=5)

today_raw = '$today'
today_dash = '$today_iso'

# 最新评分日期（兼容两种格式）
latest = conn.execute('SELECT MAX(REPLACE(date,\"-\",\"\")) FROM signal_history').fetchone()[0]

if latest is None:
    print('signal_history 无数据')
else:
    # 新鲜度检查（周末感知：周一最新=周五正常，其余工作日最新=昨日正常）
    weekday = datetime.date.today().weekday()
    latest_dt = datetime.datetime.strptime(latest, '%Y%m%d')
    delta = (datetime.date.today() - latest_dt.date()).days
    expected = datetime.date.today() - datetime.timedelta(days=(3 if weekday == 0 else 1))
    if latest_dt.date() < expected:
        print(f'评分过旧: 最新 {latest}, {delta} 天前')

    # 每日行数
    cnt = conn.execute('SELECT count(*) FROM signal_history WHERE REPLACE(date,\"-\",\"\")=?', [latest]).fetchone()[0]
    if cnt < 4000:
        print(f'{latest} 评分行数异常: {cnt} (<4000)')
    if cnt > 6000:
        print(f'{latest} 评分行数异常: {cnt} (>6000, 可能重复)')

    # 总分数据量（防止重复积累）
    total = conn.execute('SELECT count(*) FROM signal_history').fetchone()[0]
    if total > 200000:
        print(f'signal_history 总行数 {total} (>20万, 可能有重复)')

    # 评分区分度
    flat = conn.execute('SELECT count(DISTINCT final_score) FROM signal_history WHERE REPLACE(date,\"-\",\"\")=?', [latest]).fetchone()[0]
    if flat <= 1:
        print(f'final_score 无区分度 (DISTINCT={flat})')

    # fusion_score 范围是否过窄
    r = conn.execute('SELECT MIN(fusion_score), MAX(fusion_score), AVG(fusion_score) FROM signal_history WHERE REPLACE(date,\"-\",\"\")=?', [latest]).fetchone()
    if r[0] is not None:
        if r[1] - r[0] < 5:
            print(f'fusion_score 范围过窄 [{r[0]:.1f}~{r[1]:.1f}]')

    # 模型预测值是否有效
    r2 = conn.execute('SELECT count(*), AVG(reg_pred), AVG(reg40_pred) FROM signal_history WHERE REPLACE(date,\"-\",\"\")=? AND reg_pred IS NOT NULL', [latest]).fetchone()
    if r2[0] > 0 and abs(r2[1]) < 0.01 and abs(r2[2]) < 0.01:
        print(f'模型预测值几乎为零: reg20_avg={r2[1]:.4f}, reg40_avg={r2[2]:.4f}')

conn.close()
" 2>/dev/null)
while IFS= read -r line; do
    [ -n "$line" ] && alert "评分链" "$line"
done <<< "$out"


# ═══════════════════════════════════════════════════════
# 4. 信号链 — watchlist + 融合评分
# ═══════════════════════════════════════════════════════

out=$(python3 -c "
import sqlite3, datetime
conn = sqlite3.connect('$STATE_DB', timeout=5)

# watchlist 最近更新（scan_date 混 YYYY-MM-DD/YYYYMMDD 双格式，必须 REPLACE 归一后取 MAX）
latest_wl = conn.execute('SELECT MAX(REPLACE(scan_date,\"-\",\"\")) FROM watchlist').fetchone()[0]
if latest_wl:
    try:
        lw = datetime.datetime.strptime(latest_wl, '%Y%m%d').date()
        delta = (datetime.date.today() - lw).days
        weekday = datetime.date.today().weekday()
        # 周末感知：周一最新=周五(3天)正常，其余工作日最新=昨日(1天)正常
        expected = datetime.date.today() - datetime.timedelta(days=(3 if weekday == 0 else 1))
        if lw < expected:
            print(f'watchlist {delta} 天未更新 (最新 {latest_wl})')
    except: pass
else:
    print('watchlist 无数据')

# pending 数量
pending = conn.execute('SELECT count(*) FROM watchlist WHERE status=\"pending\"').fetchone()[0]
if pending == 0:
    print('watchlist 无 pending 候选')
if pending > 100:
    print(f'watchlist pending 过多: {pending}')

# fusion_3f 评分
try:
    f3 = conn.execute('SELECT MAX(REPLACE(date,\"-\",\"\")), count(*) FROM fusion_3f_signals').fetchone()
    if f3[0]:
        delta = (datetime.date.today() - datetime.datetime.strptime(f3[0], '%Y%m%d').date()).days
        if delta > 3 and weekday < 5:
            print(f'fusion_3f_signals {delta} 天未更新 (最新 {f3[0]})')
    else:
        print('fusion_3f_signals 无数据')
except: pass

# etf_scores
try:
    es = conn.execute('SELECT MAX(scan_date), count(*) FROM etf_scores').fetchone()
    if es[0]:
        delta = (datetime.date.today() - datetime.date.fromisoformat(es[0])).days
        if delta > 5 and weekday < 5:
            print(f'etf_scores {delta} 天未更新 (最新 {es[0]})')
    else:
        print('etf_scores 无数据')
except: pass

conn.close()
" 2>/dev/null)
while IFS= read -r line; do
    [ -n "$line" ] && alert "信号链" "$line"
done <<< "$out"


# ═══════════════════════════════════════════════════════
# 5. 风控链 — 盘中决策 + 执行
# ═══════════════════════════════════════════════════════

# 实时价格检查（仅交易时段严格检查）
out=$(python3 -c "
import sys
sys.path.insert(0, '$BASE')
from core.prices import fetch_price_live
# 持仓股价格
for code in ['600508', '600963']:
    p, chg = fetch_price_live(code)
    if p is None or p <= 0:
        print(f'持仓 {code} 实时价获取失败')
        break
    elif p < 1:
        print(f'持仓 {code} 价格异常: {p}')
" 2>/dev/null)
while IFS= read -r line; do
    [ -n "$line" ] && alert "风控链" "$line"
done <<< "$out"

# pending orders 检查
if [ -f "$BASE/orders/pending.json" ]; then
    age=$(( $(date +%s) - $(stat -f%m "$BASE/orders/pending.json") ))
    # 检查是否包含新信号（非空）
    signal_count=$(python3 -c "
import json
try:
    d = json.load(open('$BASE/orders/pending.json'))
    print(len(d.get('signals', [])))
except: print(-1)
" 2>/dev/null)
    if [ "$signal_count" = "-1" ]; then
        alert "风控链" "pending.json 解析失败"
    fi
    # 过期订单告警（超过4小时未执行）
    if [ "$age" -gt 14400 ] && [ "$signal_count" -gt 0 ]; then
        alert "风控链" "pending.json 中存在 $signal_count 条超过 4 小时的未执行订单"
    fi
fi

# 执行日志
out=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$STATE_DB', timeout=5)
# 检查是否有失败的执行
bad = conn.execute(\"SELECT count(*) FROM execution_logs WHERE status='FAILED' AND exec_time > datetime('now', '-7 days')\").fetchone()[0]
if bad > 3:
    print(f'过去7天有 {bad} 条失败执行记录')
conn.close()
" 2>/dev/null)
while IFS= read -r line; do
    [ -n "$line" ] && warn "风控链" "$line"
done <<< "$out"


# ═══════════════════════════════════════════════════════
# 6. IC 监控链
# ═══════════════════════════════════════════════════════

out=$(python3 -c "
import sqlite3, datetime
conn = sqlite3.connect('$STATE_DB', timeout=5)

# ic_daily
try:
    ic = conn.execute('SELECT MAX(signal_date), count(*) FROM ic_daily').fetchone()
    if ic[0]:
        try:
            dt = datetime.datetime.strptime(str(ic[0])[:10] if len(str(ic[0]))>=10 else str(ic[0]), '%Y-%m-%d' if '-' in str(ic[0]) else '%Y%m%d')
            delta = (datetime.datetime.now() - dt).days
            if delta > 5 and datetime.date.today().weekday() < 5:
                print(f'ic_daily {delta} 天未更新 (最新 {ic[0]})')
        except: pass
    else:
        print('ic_daily 无数据')
except Exception as e:
    print(f'ic_daily: {str(e)[:60]}')

# factor_ic_roll
try:
    fir = conn.execute('SELECT MAX(as_of_date), count(*) FROM factor_ic_roll').fetchone()
    if not fir[0]:
        print('factor_ic_roll 无数据')
except: pass

conn.close()
" 2>/dev/null)
while IFS= read -r line; do
    [ -n "$line" ] && alert "IC监控链" "$line"
done <<< "$out"


# ═══════════════════════════════════════════════════════
# 7. 模型链 — 模型文件完整性
# ═══════════════════════════════════════════════════════

models=(
    "$BASE/models/lgb_reg_10d_v3.txt"
    "$BASE/models/lgb_reg_20d_mac_v1.txt"
    "$BASE/models/lgb_reg_40d_new_stkfactor.txt"
    "$BASE/models/lgb_reg_etf_20d_v1.txt"
)
for m in "${models[@]}"; do
    name=$(basename "$m")
    if [ -f "$m" ]; then
        size=$(stat -f%z "$m")
        if [ "$size" -lt 10000 ]; then
            alert "模型链" "$name 体积过小 ($((size/1024))KB)"
        fi
    else
        # 模型文件可能不在标准位置，不报 alert，只报 warn 方便排查
        warn "模型链" "$name 不存在于 models/"
    fi
done


# ═══════════════════════════════════════════════════════
# 8. 备份链
# ═══════════════════════════════════════════════════════

backup_dir="$BASE/db_backups"
if [ -d "$backup_dir" ]; then
    latest_bak=$(ls -t "$backup_dir"/tushare.db.*.bak 2>/dev/null | head -1)
    if [ -n "$latest_bak" ]; then
        bak_time=$(stat -f%m "$latest_bak")
        bak_age=$(( $(date +%s) - bak_time ))
        bak_days=$((bak_age / 86400))
        if [ "$bak_days" -gt 7 ]; then
            alert "备份链" "最新 tushare.db 备份已是 ${bak_days} 天前"
        fi
    else
        alert "备份链" "db_backups 目录无 tushare.db 备份"
    fi
else
    alert "备份链" "db_backups 目录不存在"
fi


# ═══════════════════════════════════════════════════════
# 9. 策略账户 — 盘中 NAV 新鲜度（2026-08-24 加固）
#    prev_map 崩溃事件教训：异常被吞 exit 0，5 轮无告警 + 重复卖出累积。
#    交易时段 11:30 后（上午首轮已跑），strategy_accounts 应已写当天 NAV；
#    未写 = strategy_accounts_daily 运行失败。
#    节假日（指数无实时波动）自动跳过，与 strategy_accounts 脚本口径一致。
# ═══════════════════════════════════════════════════════
if is_trading_time && [ "$now_num" -ge 1130 ]; then
    out=$(python3 -c "
import sys
sys.path.insert(0, '$BASE')
try:
    from core.prices import fetch_price_live
    px, chg = fetch_price_live('000001')
    if not px or abs(chg) < 0.0001:
        pass  # 节假日/无行情，跳过
    else:
        import sqlite3
        c = sqlite3.connect('$STATE_DB', timeout=5)
        r = c.execute(\"SELECT MAX(REPLACE(date,'-','')) FROM strategy_accounts\").fetchone()[0]
        c.close()
        if r != '$today':
            print(f'策略账户最新 {r} ≠ 今天 $today（盘中运行失败，查 strategy_accounts_daily 日志）')
except Exception:
    pass
" 2>/dev/null)
    while IFS= read -r line; do
        [ -n "$line" ] && alert "策略账户" "$line"
    done <<< "$out"
fi


# ═══════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════

if [ -n "$ALERTS" ]; then
    REPORT=$(cat <<REPORT_EOF
🔴 交易系统异常报告 ($(date '+%Y-%m-%d %H:%M'))
═══════════════════════════════════════════════
$ALERTS
REPORT_EOF
)
    echo "$REPORT"
    if [ -n "$WARNINGS" ]; then
        REPORT="$REPORT

⚡ 警告（不阻断，但建议关注）:
$WARNINGS"
    fi
    # 推送到 QQ（stdin 传给 hermes send）
    echo "$REPORT" | hermes send -t qqbot 2>/dev/null || true
    exit 1
fi
