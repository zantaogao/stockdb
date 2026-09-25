#!/usr/bin/env python3
"""评分数据健康检查（2026-08-03 新增，挂到所有评分 cron）。
检查项：
  1. 缺失：工作日 18:30 后各评分表应有当天/最近交易日数据
  2. 复制：最近两天同股票数值 100% 相同 → 疑似复制（7/30=7/29 事件）
输出 PASS/FAIL，FAIL 需要 cron 分析修复。
"""
import sqlite3, sys
from datetime import date, datetime, timedelta
from pathlib import Path

STATE_DB = Path(__file__).resolve().parent.parent / 'signals.db'  # v2温层

# 表定义：日期列、key列、数值列（复制检测用）、缺失预期滞后天数（IC 类需次日收益 → lag=1）
# ⚠️ 2026-08-25：IC监控/ETF评分/CMMR IC 三个 cron 已全部推迟到 22:00 信号链之后（用户拍板），
#   运行时刻信号已产出 → signal_history/fusion_3f_signals/watchlist 严格预期当天（lag=0），
#   22:00 链失败会直接 FAIL 暴露。放宽分支保留仅覆盖 22:00 前的旧时刻（已无调用方，防御性保留）。
TABLES = {
    'signal_history':    ('date',       'stock_code', ['reg10', 'reg20', 'reg40', 'fusion_score', 'cmmr_score', 'fusion_score_cmmr'], True, 0),
    'fusion_3f_signals': ('date',       'stock_code', ['reg10', 'ma_decay', 'flow_alpha', 'vol_adj', 'fusion_3f_score'], True, 0),
    'watchlist':         ('scan_date',  'ts_code',    ['score'], True, 0),
    'etf_scores':        ('scan_date',  'ts_code',    ['score', 'prediction'], False, 0),  # 增量评分，不做复制检测
    'etf_ic':            ('signal_date','',           [], False, 1),  # 信号日 IC，需次日收益，最新=前一交易日
    'center_dual_ic_daily': ('date',   '',           [], False, 1),  # 中枢版+三模型组合 IC（08-27 新增，ic_daily.sh [3.5/5] 写入）
    'cmmr_ic_daily':     ('date',       '',           [], False, 1),
    'fusion_ic_daily':   ('date',       '',           [], False, 1),
}

def recent_trading_day(d):
    """最近交易日：从 d 往前找周一至周五"""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d

def main():
    now = datetime.now()
    conn = sqlite3.connect(str(STATE_DB), timeout=30)
    conn.execute("ATTACH DATABASE ? AS led", (str(STATE_DB.parent / 'ledger.db'),))  # v2: watchlist在热层
    fails = []
    print(f'=== 评分健康检查 {now:%Y-%m-%d %H:%M} ===')

    for tname, (dcol, kcol, vcols, check_dup, lag) in TABLES.items():
        # watchlist 在 v2 拆分层中归热层 ledger.db
        tbl = 'led.' + tname if tname == 'watchlist' else tname
        # 1. 缺失检查
        try:
            mx = conn.execute(f"SELECT MAX(REPLACE({dcol},'-','')) FROM {tbl}").fetchone()[0]
        except Exception as e:
            print(f'  {tname:<22} ERROR: {e}')
            fails.append(tname)
            continue
        exp = recent_trading_day(now.date())
        # 18:30 才更新的表（ETF 评分/各 IC，由 18:30 cron 链计算）：18:30 前（含 18:00 三因子
        # cron 窗口）预期前一交易日，否则 18:00-18:30 间运行必然误报 FAIL（2026-08-04 实测 4 表误报）
        # ⚠️ 2026-08-05 修复：etf_scores 是 18:30 批次并行任务（IC监控 18:30:39 可能先于
        # ETF评分 18:30:50 完成健康检查）——etf_scores 单独放宽到 19 点前预期前一交易日，
        # 避免批内竞态误报；其余 IC 表 lag=1 已足够。
        if tname in ('etf_ic', 'center_dual_ic_daily'):
            # 22:00 链时代：etf_ic 由 ic_daily.sh 第4步写入（23:35），center_dual_ic_daily 由第3.5步写入
            # （同为 23:35 链），23:35 前预期放宽 1 交易日，避免链头（etf_scoring.sh 23:20）健康检查
            # 对两表误报 FAIL（2026-08-27 实测 etf_ic）
            if now.hour < 23 or (now.hour == 23 and now.minute < 35):
                exp = recent_trading_day(exp - timedelta(days=1))
        elif tname in ('cmmr_ic_daily', 'fusion_ic_daily'):
            # 22:00 链时代：CMMR IC cron 23:50 才写 cmmr_ic_daily + fusion_ic_daily 两表，
            # 23:50 前（链头 23:20 ETF 评分 / 23:35 IC 监控）预期放宽 1 交易日，23:50 后严格检查
            if now.hour < 23 or (now.hour == 23 and now.minute < 50):
                exp = recent_trading_day(exp - timedelta(days=1))
        elif tname == 'fusion_3f_signals':
            pass  # ⚠️ 2026-08-28 修正注释：TABLES 中 lag=0（严格预期当天）。信号由 22:00 链产出，
                  # 本脚本仅被 23:20/23:35/23:50 三个 cron 调用（均在 22:00 链之后），信号已产出 → lag=0
                  # 严格检查可在 22:00 链失败时直接 FAIL 暴露。00:00-22:00 无调用方（跨天凌晨手动跑会
                  # 预期"今天"而 FAIL，属正常防御行为，非数据问题）。
        elif lag == 0 and now.hour < 18 and now.date() == exp:  # 仅对当日产出的表：18 点前预期前一交易日
            exp = recent_trading_day(exp - timedelta(days=1))
        for _ in range(lag):  # IC 类需次日收益：预期再往前推
            exp = recent_trading_day(exp - timedelta(days=1))
        exp_s = exp.strftime('%Y%m%d')
        status = 'PASS' if mx and mx >= exp_s else 'FAIL'
        if status == 'FAIL':
            fails.append(tname)
        print(f'  {tname:<22} 最新={mx} 预期>={exp_s}  {status}')

        # 2. 复制检测（全量表）
        if check_dup and kcol:
            rows = conn.execute(f"""
                SELECT {kcol}, REPLACE({dcol},'-','') FROM {tbl}
                WHERE REPLACE({dcol},'-','') >= (SELECT MAX(REPLACE({dcol},'-','')) FROM {tbl})
                ORDER BY REPLACE({dcol},'-','') DESC LIMIT 1""").fetchall()
            dates = conn.execute(f"SELECT DISTINCT REPLACE({dcol},'-','') FROM {tbl} ORDER BY 1 DESC LIMIT 2").fetchall()
            if len(dates) >= 2 and rows:
                d1, d2 = dates[0][0], dates[1][0]
                if d1 and d2:
                    q1 = conn.execute(f"SELECT {kcol}, {','.join(vcols)} FROM {tbl} WHERE REPLACE({dcol},'-','')=?", (d1,)).fetchall()
                    q2 = conn.execute(f"SELECT {kcol}, {','.join(vcols)} FROM {tbl} WHERE REPLACE({dcol},'-','')=?", (d2,)).fetchall()
                    m2 = {r[0]: tuple(r[1:]) for r in q2}
                    if q1 and len(q1) > 50:
                        same = sum(1 for r in q1 if r[0] in m2 and tuple(r[1:]) == m2[r[0]])
                        ratio = same / len(q1)
                        st = 'PASS' if ratio < 0.99 else 'FAIL'
                        if st == 'FAIL':
                            fails.append(f'{tname}@复制')
                        print(f'  {tname:<22} {d1} vs {d2} 同股票数值相同 {ratio*100:.1f}%  {st}')

    conn.close()

    # 3. stk_factor 新鲜度（tushare.db，2026-08-08 新增）
    # 背景: stk_factor_pro 当天因子 tushare 端延迟(16:00 常拉不到当天, 08-07 实盘拉空 →
    # 周末信号用滞后因子)。已加增量重试 + 周末补拉 cron(602ba6d55c20 周六10:00)。
    # 判据: stk_factor 最新 >= daily 倒数第 2 个交易日(允许 1 天上游延迟为常态)；
    #       滞后 >1 交易日 = 增量+重试+缺口回补+周末补拉全失败 → FAIL
    #       最新日行数 > daily×1.1+500 = 重复写入（08-08 双份事故: 并发踩踏 TEMP_DB 路径 → 11068 行）
    try:
        import duckdb
        td = duckdb.connect(str(Path(__file__).resolve().parent.parent / 'tushare.db'), read_only=True)
        d2 = td.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 2").fetchall()
        sf_max = td.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]
        if sf_max:
            n_sf = td.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date=?", (sf_max,)).fetchone()[0]
            n_dy = td.execute("SELECT COUNT(*) FROM daily WHERE trade_date=?", (sf_max,)).fetchone()[0]
            if n_sf > n_dy * 1.1 + 500:
                fails.append('stk_factor@行数重复')
                print(f'  stk_factor 最新日 {sf_max} 行数 {n_sf} vs daily {n_dy}  → FAIL(疑似重复)')
        td.close()
        if len(d2) >= 2:
            floor = d2[1][0]  # daily 倒数第 2 个交易日
            st = 'PASS' if sf_max and sf_max >= floor else 'FAIL'
            if st == 'FAIL':
                fails.append('stk_factor')
            print(f'  {"stk_factor":<22} 最新={sf_max} 允许下限={floor}  {st}')
        else:
            print(f'  stk_factor 检查跳过: daily 交易日不足 2 天')
    except Exception as e:
        print(f'  stk_factor 检查跳过: {str(e)[:80]}')  # 连接失败不误报

    # 3.5 stock_basic 存在性（signals.db，2026-09-02 新增）
    # 背景: 08-29 v2 存储迁移把 state.db 冻结为只读后, signals.db 漏迁 stock_basic 表,
    #       fusion_3f_engine 的 SQL JOIN stock_basic 从 08-31 起必失败, 但因 .sh 无 set -e
    #       静默继续 → fusion_3f_signals 欠账两天 cron 却显示 ✅。加存在性检查让漏表当天 FAIL。
    try:
        sc = sqlite3.connect(str(STATE_DB), timeout=10)
        sb_cnt = sc.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
        sc.close()
        st = 'PASS' if sb_cnt and sb_cnt > 5000 else 'FAIL'
        if st == 'FAIL':
            fails.append('stock_basic@缺失或行数异常')
            print(f'  {"stock_basic":<22} 行数={sb_cnt} 预期>5000  {st}')
        else:
            print(f'  {"stock_basic":<22} 行数={sb_cnt}  {st}')
    except Exception as e:
        fails.append('stock_basic@表缺失')
        print(f'  stock_basic 检查失败(表缺失?): {str(e)[:80]}')

    # 4. tdx_intraday_feat 新鲜度（signals.db，2026-08-16 新增）
    # 背景: 2026-08-13 起 PC 关机 → pytdx 直连改造前的旧链路拿不到分钟数据,
    #       tdx_intraday_feat 停在 8/11 共 3 个交易日无感知 → 执行端尾盘急拉/诱多
    #       过滤静默失效(查询空集=不排除不写日志)。加新鲜度检查让断链当天告警。
    # 判据: tdx_intraday_feat 最新日 >= daily 最新交易日(同日同步, 16:10 跑, 允许当天)。
    #       滞后 >0 交易日 = 拉取/聚合失败 → FAIL。
    #       ⚠️ 与 stk_factor 不同: stk_factor 是 tushare 上游延迟(允许滞后1天),
    #       tdx_intraday_feat 是本地 pytdx 直连(应当天同步), 所以严格到当天。
    try:
        sc = sqlite3.connect(str(STATE_DB), timeout=10)  # v2温层
        tdx_max = sc.execute("SELECT MAX(date) FROM tdx_intraday_feat").fetchone()[0]
        sc.close()
        if tdx_max and d2:
            d_latest = d2[0][0]  # daily 最新交易日
            st = 'PASS' if str(tdx_max) >= str(d_latest) else 'FAIL'
            if st == 'FAIL':
                fails.append('tdx_intraday_feat')
            print(f'  {"tdx_intraday_feat":<22} 最新={tdx_max} 预期={d_latest}  {st}')
        else:
            print(f'  tdx_intraday_feat 检查跳过: 无数据或 daily 为空')
    except Exception as e:
        print(f'  tdx_intraday_feat 检查跳过: {str(e)[:80]}')  # 连接失败不误报

    # 4b. tdx_intraday_feat 覆盖率（2026-09-03 新增）
    # 背景: 8月缺口(0812~0831)期间每日都有行但只有1~12股，MAX(date)新鲜度检查看不出来。
    # 判据: 最近5个交易日的每日覆盖股数 >= 4000，低于则FAIL。
    try:
        sc = sqlite3.connect(str(STATE_DB), timeout=10)
        cov = sc.execute(
            "SELECT date, COUNT(*) FROM tdx_intraday_feat "
            "WHERE date <= ? GROUP BY date ORDER BY date DESC LIMIT 5",
            (int(d2[0][0]),)).fetchall() if d2 else []
        sc.close()
        low = [(str(x), n) for x, n in cov if n < 4000]
        st = 'PASS' if cov and not low else 'FAIL'
        if st == 'FAIL':
            fails.append('tdx_feat_coverage')
        print(f'  {"tdx_feat_coverage":<22} 近5日={[str(x) for x,_ in cov]} 低覆盖日={low if low else "无"}  {st}')
    except Exception as e:
        print(f'  tdx_feat_coverage 检查跳过: {str(e)[:80]}')

    print()
    if fails:
        print(f'❌ 检查未通过: {fails}')
        sys.exit(1)
    print('✅ 全部通过')

if __name__ == '__main__':
    main()
