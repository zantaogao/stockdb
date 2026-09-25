#!/usr/bin/env python3
"""每日盘后报告 v3（2026-08-06，深度版）
内容：
  ①今日市场概况（指数/成交额+量能5·20日均/涨跌家数+宽度对比/涨跌停/领涨领跌板块+近5日持续性）
  ②账户情况（主账户+三策略账户，含行业分布/今日贡献/风控距离预警/累计超额）
  ③评分Top10（2026-09-11 用户拍板：CMMR独立/CMMR+ 全通道停推 → 保留 三模型融合/中枢版/中枢版+三模型/10d独立）
  ③b 信号验证（昨日Top10今日表现/近5日模型IC/强买次日超额）
  ④明日策略（重评窗口/watchlist重点观察/大盘状态）
  ⑤系统流程检查（health_verify 8链 + 每日 cron 逐一状态核对 + 数据新鲜度）
推送：hermes send -t qqbot（无幂等）；默认只打印不推送，加 --push 才推（09-02改，防手动验证误推）
"""
import sqlite3, duckdb, subprocess, sys, json, os
from pathlib import Path
from datetime import date, datetime

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))  # 保证 from core.prices import 可用（cron wrapper 可能不在 stockdb cwd）
STATE_DB = BASE / 'signals.db'
TUSHARE_DB = BASE / 'tushare.db'
# 推送目标（2026-08-31 用户拍板：QQ 只推主号；旧主号 2D719CDE 已注销）
QQ_TARGETS = [
    'qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616',                           # 主 QQ（主人）
]
INIT_CAPITAL = 1_000_000.0
REBALANCE_INTERVAL = 10   # 兜底值：账户未在 strategy_accounts_daily.ACCOUNTS 显式配 rebalance 时用
# 重评窗口单一来源 = strategy_accounts_daily.ACCOUNTS[aid]['rebalance']（2026-09-11 去硬编码：
# 原实现把 fusion_dual/center_dual=15、其余 10 写死在这里，规则一改显示就漂移，与 _cron_daily_audit
# 账户列表动态化同一教训）。导入失败 → 退回 REBALANCE_INTERVAL 并在报告里显式告警。
try:
    sys.path.insert(0, str(BASE / 'scripts'))
    from strategy_accounts_daily import ACCOUNTS as _STRAT_ACCOUNTS
    _RE_IMPORT_ERR = ''
except Exception as _e:
    _STRAT_ACCOUNTS = {}
    _RE_IMPORT_ERR = f'{type(_e).__name__}: {_e}'
# 2026-09-11 用户拍板：cmmr/cmmr_fusion 移出（全通道停推，账户照常运行）
# 2026-09-17 用户拍板：恢复 cmmr 系进报告（两榜+净值+次日超额全部回补）
STRATEGY_NAMES = {'fusion3f': '三因子融合', 'cmmr': 'CMMR独立', 'cmmr_fusion': 'CMMR+', 'fusion_center': '中枢版Top10', 'fusion_dual': '三因子+三模型', 'center_dual': '中枢版+三模型', 'agent_auto': 'Agent全权', 'reg10_solo': '10d独立', 'cmmr_clf': 'CMMR+clf门票'}

# 每日链 cron 核对表：job 名关键字 → 用途（模糊匹配）
# 2026-08-31 本机版：对齐本机实际 cron 链（M2 版含信号扫描/Top10推送，本机没有）
DAILY_CHAIN = [
    ('A股数据增量更新', '数据更新'),
    ('TDX分钟数据同步', 'TDX分钟'),
    ('技术指标自算', '指标自算'),
    ('ETF 净值更新', 'ETF净值'),
    ('策略账户日更', '策略日更'),
    # 2026-09-04 用户拍板：三因子回测移出报告（三因子系已证伪，账户与回测照跑不进报告）
    # 2026-09-11 停推时曾移除 CMMR 两行；2026-09-17 用户拍板恢复
    ('CMMR双策略等权回测', 'CMMR回测'),
    ('每日账目对账', '账目对账'),
    ('全系统备份', '备份'),
    ('stk_factor补拉', '因子补拉'),
    ('双轨信号对比', '双轨对比'),
    # 2026-09-11 修正：原「盘中意见-夜间简报」cron 已不存在（night_opinion_brief.py 现由 23:55
    #   每日综合报告 job 内调用）→ 从核对表移除，消除每日假告警
    ('ETF 全市场评分', 'ETF评分'),
    ('每日 IC 监控', 'IC监控'),
    ('CMMR IC 每日计算', 'CMMR IC'),
]

def get_st_names():
    try:
        td = duckdb.connect(str(TUSHARE_DB), read_only=True)
        sb = {}
        for r in td.execute("SELECT ts_code, name, market, industry FROM stock_basic").fetchall():
            sb[r[0].split('.')[0]] = (r[1], r[2], r[3])
        td.close()
        return sb
    except Exception:
        return {}

_INDEX_BENCH_CACHE = {}
def _index_bench_pct(end_date, start_date=None):
    """基准累计涨幅%（中证1000 官方收盘价，tushare.db）。
    2026-09-17 用户拍板：超额基准不再用账本 market_ret 复利——那是记账时点的
    盘中瞬时值（20260804 低记 2.5pp 导致 cmmr 两户超额虚高 3pp+）。
    start_date=None → 用账户自身首日（保持与旧口径同起点）。结果缓存。"""
    key = (end_date, start_date)
    if key in _INDEX_BENCH_CACHE:
        return _INDEX_BENCH_CACHE[key]
    td = duckdb.connect(str(TUSHARE_DB), read_only=True)
    try:
        rows = td.execute(
            "SELECT date, close FROM index_daily WHERE index_code='000852' ORDER BY date").fetchall()
    finally:
        td.close()
    conv = lambda s: f"{str(s)[:4]}-{str(s)[4:6]}-{str(s)[6:8]}" if '-' not in str(s) else str(s)
    end_c = conv(end_date)
    start_c = conv(start_date) if start_date else None
    seq = [c for d, c in rows if (start_c is None or str(d) >= start_c) and str(d) <= end_c]
    if len(seq) < 2:
        raise ValueError('指数数据不足')
    pct = (seq[-1] / seq[0] - 1) * 100
    # 首日涨幅（seq[0] 当日相对前一日）计入，与账本首日 market_ret 口径一致
    all_dates = [(str(d), c) for d, c in rows]
    for i, (d, c) in enumerate(all_dates):
        if d == (start_c or end_c) and i > 0:
            pct += (c / all_dates[i-1][1] - 1) * 100
            break
    pct = round(pct, 4)
    _INDEX_BENCH_CACHE[key] = pct
    return pct

def ts_code(code):
    """裸码 → tushare ts_code（与 strategy_accounts_daily 同逻辑）"""
    s = str(code)
    if s.startswith(('6', '68', '689', '9')):
        return f'{s}.SH'
    return f'{s}.SZ'


def last_close(tushare, tc, max_date):
    """持仓股在 ≤max_date 的最近收盘价（2026-09-04 修复：停牌/新股无当日行时
    向前取最近可得——停牌期价格不变，市值按最后收盘价估值，避免归零假亏）。
    查不到返回 None（新股无任何历史行时由调用方兜底 avg_cost）。"""
    try:
        r = tushare.execute(
            "SELECT close FROM daily WHERE ts_code=? AND trade_date<=? "
            "ORDER BY trade_date DESC LIMIT 1", (tc, str(max_date))).fetchone()
        return float(r[0]) if r and r[0] else None
    except Exception:
        return None


def holding_days(buy_date, today=None):
    """持仓天数（交易日口径，2026-08-18 与面板/后台决策统一 core/hold_days.py）。
    原自然日口径周末/节假日多算，导致规则5B(持仓≥20天)误判超期卖出候选。
    兼容 YYYY-MM-DD 和 YYYYMMDD 两种格式。"""
    try:
        from core.hold_days import calc_holding_days
        return calc_holding_days(buy_date)
    except Exception:
        try:
            bd = str(buy_date).replace('-', '')
            b = date(int(bd[:4]), int(bd[4:6]), int(bd[6:8]))
            t = today or date.today()
            return (t - b).days
        except Exception:
            return None

def is_bad(sb, code):
    info = sb.get(code)
    if not info:
        return False
    name, market, _ = info
    return (name and 'ST' in name.upper()) or market == '北交所' or code.startswith(('8', '4', '92'))

def check_cron_chain(today_ymd):
    """核对每日链 cron 运行状态（jobs.json 权威；名称模糊匹配，today 用最新交易日）"""
    try:
        data = json.load(open(Path.home() / '.hermes' / 'cron' / 'jobs.json'))
        jobs = data.get('jobs', data if isinstance(data, list) else [])
    except Exception as e:
        return [f"⚠️ 读 jobs.json 失败: {e}"]
    lines = []
    for name, label in DAILY_CHAIN:
        # 模糊匹配：job 名包含 DAILY_CHAIN 关键字
        j = next((x for x in jobs if name in str(x.get('name', ''))), None)
        if not j:
            lines.append(f"  ⚠️ {label}: 找不到「{name}」")
            continue
        lr = str(j.get('last_run_at') or '')
        st = j.get('last_status')
        # 2026-09-11：已停用的 job 显示 ⏸ 而非 ⚠️，避免每日假告警
        if j.get('enabled') is False:
            lines.append(f"  ⏸ {label}: 已停用（用户拍板，不在每日链）")
            continue
        ok = (st == 'ok')
        # last_run 日期提取（2026-08-04T16:49 → 20260804）
        lr_date = lr[:10].replace('-', '')
        ran_today = (lr_date == today_ymd.replace('-', ''))
        mark = '✅' if (ok and ran_today) else ('⚠️' if ok else '❌')
        time_s = lr[11:16] if len(lr) >= 16 else '?'
        note = '' if (ok and ran_today) else (f'（{st}，最近 {lr[5:16]}）' if not ran_today else f'（状态{st}）')
        lines.append(f"  {mark} {label}: {time_s} {note}")
    return lines

def run_health_verify():
    """调 health_verify.py 拿系统健康检查结果"""
    try:
        r = subprocess.run([sys.executable, '-B', str(BASE / 'scripts' / 'health_verify.py')],
                           capture_output=True, timeout=120, text=True)
        out = r.stdout + r.stderr
        fails = [l for l in out.splitlines() if '[FAIL]' in l]
        all_ok = '全部检查通过' in out
        return out, fails, all_ok
    except Exception as e:
        return f"health_verify 调用失败: {e}", [], False

def tail_alerts(state, sb, d3):
    """③a 尾盘异动预警行（2026-08-08 TDX 分钟数据；2026-09-11 抽函数 + 排序显式化）。

    修的问题：原 `entrap` 用集合推导收集（`{r[0] for r in ...}`），输出顺序随进程
    PYTHONHASHSEED 变化 → 同一份数据两次运行报告行序不同（9/11 发现 688191 与 002487
    两条诱多行互换）。现在七组列表全部显式排序：急拉/最后5分钟急拉按幅度降序、
    下跌按幅度升序、诱多按振幅降序（并把开跌/VWAP/振幅三个判据值打出来，让排序可见）。
    另：`.bak` 版 [:5] 取的是**字典/集合遍历顺序的前 5**（不是最大的 5），现在是幅度前 5。
    """
    out = []
    try:
        tail30 = {r[0]: r[1] for r in state.execute(
            "SELECT code, tail30_ret FROM tdx_intraday_feat WHERE date=? AND tail30_ret > 0.015 AND vwap_dev > 0", (d3,)).fetchall()}
        # 2026-09-02 分钟线挖掘新增: 最后5分钟急拉（不看VWAP, 次日中位-1.23%, 5/5月为负）
        tail5_only = {r[0]: r[1] for r in state.execute(
            "SELECT code, tail5_ret FROM tdx_intraday_feat WHERE date=? AND tail5_ret > 0.015", (d3,)).fetchall()}
        tail5_only = {k: v for k, v in tail5_only.items() if k not in tail30}
        low_abs = {r[0]: r[1] for r in state.execute(
            "SELECT code, tail30_ret FROM tdx_intraday_feat WHERE date=? AND tail30_ret < -0.005", (d3,)).fetchall()}
        # 诱多组合带三个判据值（排序 + 展示都需要）
        entrap = {r[0]: (r[1], r[2], r[3]) for r in state.execute(
            "SELECT code, open30_ret, vwap_dev, amp_intra FROM tdx_intraday_feat "
            "WHERE date=? AND open30_ret < 0 AND vwap_dev > 0 AND amp_intra > 0.05", (d3,)).fetchall()}
        if tail30 or tail5_only or low_abs or entrap:
            cand = {r[0] for r in
                    state.execute("SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=? LIMIT 200", (d3,)).fetchall()}
            held = {r[0] for r in state.execute("SELECT code FROM led.holdings WHERE status='hold'").fetchall()}
            warn_top = sorted((c for c in tail30 if c in cand), key=lambda c: -tail30[c])
            warn_held = sorted((c for c in tail30 if c in held), key=lambda c: -tail30[c])
            t5_top = sorted((c for c in tail5_only if c in cand), key=lambda c: -tail5_only[c])
            t5_held = sorted((c for c in tail5_only if c in held), key=lambda c: -tail5_only[c])
            low_top = sorted((c for c in low_abs if c in cand), key=lambda c: low_abs[c])
            low_held = sorted((c for c in low_abs if c in held), key=lambda c: low_abs[c])
            ent_top = sorted((c for c in entrap if c in cand or c in held), key=lambda c: -entrap[c][2])
            out.append("【尾盘异动预警】(TDX分钟)")
            if ent_top:
                for c in ent_top[:5]:
                    nm = sb.get(c, ('', '', ''))[0] or ''
                    o30, vd, amp = entrap[c]
                    out.append(f"  🚫 {c} {nm} 诱多组合(开跌 {o30*100:+.1f}% + VWAP {vd*100:+.1f}% + 振幅 {amp*100:.1f}%) → 次日谨慎(中位-1.09%)")
            if warn_top:
                for c in warn_top[:5]:
                    nm = sb.get(c, ('', '', ''))[0] or ''
                    out.append(f"  ⚠️ {c} {nm} 尾盘急拉 {tail30[c]*100:+.1f}% → 次日谨慎(出货式拉升, 次日中位-1.32%)")
            if warn_held:
                for c in warn_held[:5]:
                    nm = sb.get(c, ('', '', ''))[0] or ''
                    out.append(f"  ⚠️ 持仓 {c} {nm} 尾盘急拉 {tail30[c]*100:+.1f}% → 次日冲高可止盈(出货式)")
            if t5_top:
                for c in t5_top[:5]:
                    nm = sb.get(c, ('', '', ''))[0] or ''
                    out.append(f"  ⚠️ {c} {nm} 最后5分钟急拉 {tail5_only[c]*100:+.1f}% → 次日谨慎(尾盘突击诱多, 次日中位-1.23%)")
            if t5_held:
                for c in t5_held[:5]:
                    nm = sb.get(c, ('', '', ''))[0] or ''
                    out.append(f"  ⚠️ 持仓 {c} {nm} 最后5分钟急拉 {tail5_only[c]*100:+.1f}% → 次日冲高可止盈(尾盘突击)")
            if low_top:
                for c in low_top[:5]:
                    nm = sb.get(c, ('', '', ''))[0] or ''
                    out.append(f"  ✚ {c} {nm} 尾盘跌 {low_abs[c]*100:+.1f}% → 低吸观察(明日开盘走强可低吸, 历史次日中位+0.55%)")
            if low_held:
                for c in low_held[:5]:
                    nm = sb.get(c, ('', '', ''))[0] or ''
                    out.append(f"  ✚ 持仓 {c} {nm} 尾盘跌 {low_abs[c]*100:+.1f}% → 次日开盘走强可加仓观察")
            if not warn_top and not warn_held and not t5_top and not t5_held and not low_top and not low_held:
                out.append("  ✅ 信号/持仓无尾盘异动")
            out.append("")
    except Exception as e:
        out.append(f"【尾盘异动预警】跳过: {str(e)[:60]}")
        out.append("")
    return out


def main():
    state = sqlite3.connect(str(STATE_DB), timeout=30)  # v2: 主连=signals.db(温层), 信号表直接读
    state.execute("ATTACH DATABASE ? AS led", (str(BASE / 'ledger.db'),))  # v2: 账本表用 led. 前缀
    tushare = duckdb.connect(str(TUSHARE_DB), read_only=True)
    sb = get_st_names()
    today = date.today().strftime('%Y%m%d')
    last_td = str(tushare.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0])
    d3 = str(state.execute("SELECT MAX(REPLACE(date,'-','')) FROM signal_history").fetchone()[0] or '')
    df = str(state.execute("SELECT MAX(REPLACE(date,'-','')) FROM fusion_3f_signals").fetchone()[0] or '')

    issues = []  # 收集系统异常（放头部）
    lines = [f"📊 每日盘后报告 {last_td}", ""]

    # ═══ ① 市场概况 ═══
    lines.append("【市场概况】")
    idx_rows = tushare.execute(
        "SELECT ts_code, close, pct_chg FROM index_daily_raw WHERE trade_date=? "
        "AND ts_code IN ('000001.SH','399001.SZ','399006.SZ','000852.SH')", (last_td,)).fetchall()
    idx_map = {r[0]: (r[1], r[2]) for r in idx_rows}
    # 指数若滞后（index 与 daily 不同步），用实时价补充
    # ⚠️ 2026-09-05 修复：库查询漏 000852.SH → 数据正常时中证1000 反而缺失
    # （实时补充分支才有它）；统一 key 用标准 ts_code
    if not idx_map or last_td != str(tushare.execute("SELECT MAX(trade_date) FROM index_daily_raw").fetchone()[0]):
        try:
            from core.prices import fetch_price_live
            live_map = {'000001': ('000001.SH', '上证指数'), '399001': ('399001.SZ', '深证成指'),
                        '399006': ('399006.SZ', '创业板指'), '000852': ('000852.SH', '中证1000')}
            for code, (key, label) in live_map.items():
                px, chg = fetch_price_live(code)
                if px:
                    idx_map[key] = (px, chg)
        except Exception:
            pass
    for code, label in [('000001.SH', '上证指数'), ('399001.SZ', '深证成指'), ('399006.SZ', '创业板指'),
                        ('000852.SH', '中证1000')]:
        entry = idx_map.get(code) or idx_map.get(code.split('.')[0]) or idx_map.get('中证1000' if code == '000852.SH' else '')
        if entry:
            c, pct = entry
            arrow = '🔴' if pct > 0 else '🟢'
            lines.append(f"  {label} {c:>10.2f}  {pct:+.2f}% {arrow}")
    # 成交额（amount 单位千元 → 元 → 亿）+ 环比昨日
    amt = tushare.execute("SELECT SUM(amount)*1000 FROM daily WHERE trade_date=?", (last_td,)).fetchone()[0]
    amt_prev = None
    prev_td0 = str(tushare.execute(
        "SELECT MAX(trade_date) FROM daily WHERE trade_date < ?", (last_td,)).fetchone()[0])
    if prev_td0:
        amt_prev = tushare.execute("SELECT SUM(amount)*1000 FROM daily WHERE trade_date=?", (prev_td0,)).fetchone()[0]
    if amt:
        s = f"  全市场成交额 {amt/1e8:,.0f} 亿元"
        if amt_prev and amt_prev > 0:
            s += f"（较昨 {amt/amt_prev*100-100:+.1f}%）"
        lines.append(s)
    # 量能趋势：5日/20日均额对比（2026-08-06 深度版）
    try:
        amt_hist = [r[0] for r in tushare.execute(
            "SELECT SUM(amount)*1000 FROM daily WHERE trade_date <= ? GROUP BY trade_date ORDER BY trade_date DESC LIMIT 20",
            (last_td,)).fetchall()]
        amt_hist = [a for a in amt_hist if a]
        if len(amt_hist) >= 5:
            ma5 = sum(amt_hist[:5]) / 5
            ma20 = sum(amt_hist) / len(amt_hist)
            lines.append(f"  量能: 5日均额 {ma5/1e8:,.0f} 亿（今 {amt/ma5*100-100:+.1f}%）  20日均额 {ma20/1e8:,.0f} 亿（今 {amt/ma20*100-100:+.1f}%）")
    except Exception:
        pass
    # 涨跌家数
    up = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg>0", (last_td,)).fetchone()[0]
    total = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=?", (last_td,)).fetchone()[0]
    flat = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg=0", (last_td,)).fetchone()[0]
    dn = total - up - flat
    up_s = f"（涨占比 {up/total*100:.0f}%）"
    if prev_td0:
        try:
            up_p = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg>0", (prev_td0,)).fetchone()[0]
            tot_p = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=?", (prev_td0,)).fetchone()[0]
            if tot_p:
                up_s += f"，昨 {up_p/tot_p*100:.0f}%"
        except Exception:
            pass
    lines.append(f"  全市场 {total} 只：涨 {up} / 平 {flat} / 跌 {dn}{up_s}")
    # 涨跌停（stk_limit 或 pct_chg 阈值）
    zt = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg>=9.8", (last_td,)).fetchone()[0]
    dt = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg<=-9.8", (last_td,)).fetchone()[0]
    lines.append(f"  涨停 {zt} 只 / 跌停 {dt} 只")
    # 涨幅分布（>5% 强势股数、<-5% 弱势股数）
    strong = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg>5", (last_td,)).fetchone()[0]
    weak = tushare.execute("SELECT COUNT(*) FROM daily WHERE trade_date=? AND pct_chg<-5", (last_td,)).fetchone()[0]
    lines.append(f"  强势(>5%) {strong} 只 / 弱势(<-5%) {weak} 只")
    # 领涨/领跌行业（按日涨幅均值的 top/bottom 行业）
    try:
        ind = tushare.execute("""
            SELECT b.industry, AVG(d.pct_chg) FROM daily d
            JOIN stock_basic b ON b.ts_code = d.ts_code
            WHERE d.trade_date=? AND b.industry IS NOT NULL AND b.industry != ''
            GROUP BY 1 HAVING COUNT(*)>=10 ORDER BY 2 DESC
        """, (last_td,)).fetchall()
        if ind:
            top3 = ind[:3]
            bot3 = ind[-3:]
            lines.append("  领涨板块: " + "  ".join(f"{n} {v:+.1f}%" for n, v in top3))
            lines.append("  领跌板块: " + "  ".join(f"{n} {v:+.1f}%" for n, v in bot3))
            # 板块轮动：对比昨日领涨/领跌
            if prev_td0:
                ind_prev = {r[0]: r[1] for r in tushare.execute("""
                    SELECT b.industry, AVG(d.pct_chg) FROM daily d
                    JOIN stock_basic b ON b.ts_code = d.ts_code
                    WHERE d.trade_date=? AND b.industry IS NOT NULL AND b.industry != ''
                    GROUP BY 1 HAVING COUNT(*)>=10
                """, (prev_td0,)).fetchall()}
                chg_notes = []
                for n, v in top3:
                    pv = ind_prev.get(n)
                    chg_notes.append(f"{n} {v:+.1f}%" + (f"(昨{pv:+.1f}%)" if pv is not None else ""))
                lines.append("  强势延续: " + "  ".join(chg_notes))
            # 板块持续性：近5日日均涨幅×5 ≈ 累计（脉冲 vs 持续）（2026-08-06 深度版）
            try:
                tds5 = [r[0] for r in tushare.execute(
                    "SELECT DISTINCT trade_date FROM daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 5",
                    (last_td,)).fetchall()]
                ph5 = ','.join(['?'] * len(tds5))
                notes5 = []
                for n, _ in top3:
                    rows5 = tushare.execute(f"""
                        SELECT AVG(d.pct_chg) FROM daily d JOIN stock_basic b ON b.ts_code = d.ts_code
                        WHERE d.trade_date IN ({ph5}) AND b.industry = ?""", tds5 + [n]).fetchall()
                    if rows5 and rows5[0][0] is not None:
                        notes5.append(f"{n} 近5日{rows5[0][0]*5:+.1f}%")
                if notes5:
                    lines.append("  板块持续性: " + "  ".join(notes5))
            except Exception:
                pass
    except Exception:
        pass
    # —— 市场定性：宽度 / 赚钱效应 / 风格（2026-08-07 深度版）——
    try:
        w_rows = tushare.execute("""
            SELECT trade_date, ROUND(100.0*COUNT(*) FILTER (WHERE pct_chg>0)/COUNT(*),1)
            FROM daily GROUP BY 1 ORDER BY 1 DESC LIMIT 20""").fetchall()
        if w_rows:
            w_now = w_rows[0][1]
            w_med = sorted(r[1] for r in w_rows)[len(w_rows)//2]
            w_v = '普涨' if w_now >= 70 else ('普跌' if w_now <= 30 else ('偏弱分化' if w_now < 50 else '震荡分化'))
            lines.append(f"  宽度: 涨占比 {w_now:.0f}% vs 近20日中位 {w_med:.0f}%（{w_v}）")
        z_rows = tushare.execute("""
            SELECT trade_date, COUNT(*) FILTER (WHERE pct_chg>=9.8) FROM daily
            GROUP BY 1 ORDER BY 1 DESC LIMIT 20""").fetchall()
        if z_rows:
            z_now = z_rows[0][1]
            z_med = sorted(r[1] for r in z_rows)[len(z_rows)//2]
            z_v = '强' if z_now >= z_med*1.5 else ('弱' if z_now <= z_med*0.5 else '中性')
            lines.append(f"  赚钱效应: 涨停 {z_now} 家 vs 近20日中位 {z_med} 家（{z_v}）")
        def _cum5(ts):
            rr = tushare.execute("SELECT pct_chg FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date DESC LIMIT 5", (ts,)).fetchall()
            if len(rr) < 5:
                return None
            c = 1.0
            for (p,) in rr:
                c *= (1 + float(p)/100)
            return (c - 1) * 100
        c5_zz, c5_sh = _cum5('000852.SH'), _cum5('000001.SH')
        if c5_zz is not None and c5_sh is not None:
            style = '小盘强' if c5_zz > c5_sh else ('大盘强' if c5_sh > c5_zz else '均衡')
            lines.append(f"  风格: 近5日中证1000 {c5_zz:+.1f}% vs 上证 {c5_sh:+.1f}%（{style}）")
    except Exception:
        pass
    lines.append("")

    # ═══ ② 账户情况 ═══
    lines.append("【账户情况】")
    acc = state.execute("SELECT cash_balance, total_value, initial_capital, last_update FROM led.account_balance WHERE account_id='main'").fetchone()
    if acc:
        cash, tv_old, ic, last_upd = acc
        # ⚠️ 2026-08-05 修复：account_balance.total_value 只在成交时更新（exec_agent），
        # 无成交时停留在上次成交时点 → 主账户总资产/累计收益过期。改为用收盘价实时重算：
        # 总资产 = 现金 + Σ(持仓股数 × daily[last_td] 收盘价)
        rows = state.execute("SELECT code, shares, avg_cost, buy_date FROM led.holdings WHERE status='hold'").fetchall()
        pos_value = 0.0
        pnl_rows = []  # (code, name, 持仓成本, 收盘价, 浮盈亏%, 买入日)
        for code, shares, ac, bd in rows:
            tc = ts_code(code)
            # 2026-09-04 修复：精确日 → 最近可得收盘（持仓股停牌时市值按最后收盘价计，
            # 不再归零——原代码无当日行直接跳过，停牌持仓市值变 0 → 总资产假性暴跌）
            close = last_close(tushare, tc, last_td)
            if close:
                pos_value += shares * close
                if ac and ac > 0:
                    pnl_rows.append((code, shares, ac, close, (close/ac - 1) * 100, bd))
        tv = cash + pos_value
        ret = (tv/ic - 1) * 100 if ic else 0
        # 当日收益（2026-08-24 改总资产口径，与策略账户 NAV 一致，买卖都算）：
        #   今日总资产 = 今日现金 + Σ(今日持仓×今收)
        #   昨日总资产 = 昨日现金 + Σ(昨日持仓×昨收)
        #   昨日持仓/现金 用 trade_log 反推：昨日持仓 = 今日持仓 − 今日买入 + 今日卖出；
        #   昨日现金 = 今日现金 − 今日卖出收入 + 今日买入支出
        day_ret = None
        # ⚠️ 2026-09-04 防呆：行情未含今日（daily 未更新/盘中跑）且今日已有成交时，
        # 当前持仓已含今日交易、估值日却是 last_td → 总资产/当日收益为错配假数字
        # （M2 实测手动盘中跑出 -0.11% vs 真实 -0.27%）。盘前（今日无成交）与盘后
        # （daily 已含今日）不触发；仅拦截中间态，防止报告/手动输出误导性收益。
        stale = False
        try:
            _now = datetime.now()
            _n_today = state.execute(
                "SELECT COUNT(*) FROM led.trade_log WHERE trade_date=? AND (strategy='main' OR strategy IS NULL)",
                (_now.strftime('%Y-%m-%d'),)).fetchone()[0]
            if str(last_td) < _now.strftime('%Y%m%d') and _n_today > 0:
                stale = True
        except Exception:
            pass
        if not stale:
            try:
                prev_td = str(tushare.execute(
                    "SELECT MAX(trade_date) FROM daily WHERE trade_date < ?", (last_td,)).fetchone()[0])
                td_iso = f"{str(last_td)[:4]}-{str(last_td)[4:6]}-{str(last_td)[6:8]}"  # trade_log 用 YYYY-MM-DD
                # 今日买卖（trade_log，含补记流水）
                t_buys, t_sells = {}, {}
                sell_income, buy_cost = 0.0, 0.0
                for r in state.execute(
                        "SELECT code, direction, quantity, amount FROM led.trade_log "
                        "WHERE trade_date=? AND (strategy='main' OR strategy IS NULL)", (td_iso,)).fetchall():
                    code, direction, qty, amt = r[0], r[1], r[2] or 0, r[3] or 0
                    if direction == 'BUY':
                        t_buys[code] = t_buys.get(code, 0) + qty
                        buy_cost += amt
                    elif direction == 'SELL':
                        t_sells[code] = t_sells.get(code, 0) + qty
                        sell_income += amt
                # 昨日持仓 = 今日持仓 − 今日买入 + 今日卖出
                # ⚠️ 2026-08-24：今日全清仓的股票（今日无持仓但有 SELL）必须从卖出补回昨日持仓，
                #    否则反推丢失该股票 → 昨日总资产少算（当日收益虚高，曾算出 +4.59%）
                # ⚠️ 2026-09-04 除权还原：估值日(last_td)该股有除权时，今日持仓已是送转后股数、
                #    现金已含股息 → 昨日持仓须 ÷factor 还原、昨日现金须 −净息，
                #    否则送转股被当作昨日已持有（昨日资产虚高 factor 倍）→ 除权日收益假亏
                _ca_map = {}
                for _ca in state.execute(
                        "SELECT code, factor, cash_div, tax_rate FROM led.ca_adjustments "
                        "WHERE ex_date=? AND account='main'",
                        (str(last_td),)).fetchall():
                    _ca_map[_ca[0]] = (float(_ca[1] or 1), float(_ca[2] or 0), float(_ca[3] or 0))
                yest_pos = {}
                for code, shares, ac, bd in rows:
                    yshares = shares - t_buys.get(code, 0) + t_sells.get(code, 0)
                    if code in _ca_map:
                        _f = _ca_map[code][0]
                        if _f and _f != 1.0:
                            yshares = int(round(yshares / _f))
                    if yshares > 0:
                        yest_pos[code] = yshares
                for code, s_qty in t_sells.items():
                    if code not in yest_pos and code not in t_buys:
                        yest_pos[code] = s_qty  # 今日全清仓：昨日持仓 = 卖出量
                        if code in _ca_map:
                            _f = _ca_map[code][0]
                            if _f and _f != 1.0:
                                yest_pos[code] = int(round(s_qty / _f))  # 卖出的是送转后股数
                # 昨日现金 = 今日现金 − 卖出收入 + 买入支出 − Σ净息（当日除权收到的股息不属于昨日）
                yest_cash = cash - sell_income + buy_cost
                for _cc, (_f, _cd, _tr) in _ca_map.items():
                    if _cc in yest_pos:
                        yest_cash -= yest_pos[_cc] * _cd * (1 - _tr)
                # 昨日总资产（昨收估值）
                yest_asset = yest_cash
                for code, yshares in yest_pos.items():
                    tc = ts_code(code)
                    # 2026-09-04 修复：昨收估值同样走最近可得收盘兜底（昨日停牌/复牌首日
                    # 无 prev_td 行时不再漏估 → 昨日资产少算 → 当日收益虚高的旧缺陷）
                    yc = last_close(tushare, tc, prev_td)
                    if yc:
                        yest_asset += yshares * yc
                # 今日总资产（今收估值，pos_value 已算）
                cur_asset = cash + pos_value
                if yest_asset > 0:
                    day_ret = (cur_asset / yest_asset - 1) * 100
            except Exception:
                pass
        lines.append(f"  主账户（中长线）: 总资产 {tv:,.0f}  现金 {cash:,.0f}  累计 {ret:+.2f}%"
                     + (f"  当日收益 {day_ret:+.2f}%（总资产口径，含持仓浮盈与当日卖出已实现盈亏）" if day_ret is not None else ""))
        if stale:
            lines.append(f"    ⚠️ 行情数据截至 {last_td}（未含今日）且今日已有成交：持仓与估值日错配，"
                         "当日收益不输出以防失真。16:00 数据更新后重跑即正常。")
        npos = len(rows)
        lines.append(f"    持仓 {npos} 只")
        # 持仓表格（2026-08-05：全量打印，等宽对齐，含持仓周期）
        name_map = {r[0]: r[1] for r in state.execute("SELECT code, name FROM led.holdings WHERE status='hold'").fetchall()}
        calc2 = []
        for code, shares, ac, close, p, bd in pnl_rows:
            calc2.append((code, name_map.get(code, code), shares, ac, close, p, holding_days(bd)))
        wins = [r for r in calc2 if r[5] > 0]
        losses = [r for r in calc2 if r[5] < 0]
        if calc2:
            lines.append(f"    盈利 {len(wins)} 只 / 亏损 {len(losses)} 只")
            lines.append("    " + "  ".join([
                f"{'代码':<6}", f"{'名称':<8}", f"{'股数':>8}", f"{'成本':>8}", f"{'现价':>8}", f"{'盈亏%':>7}", f"{'持仓':>5}"]))
            for code, nm, sh, ac, close, p, hd in sorted(calc2, key=lambda r: r[5], reverse=True):
                hd_s = f"{hd}天" if hd is not None else "-"
                lines.append("    " + "  ".join([
                    f"{code:<6}", f"{nm:<8}", f"{sh:>8,}", f"{ac:>8.2f}", f"{close:>8.2f}", f"{p:>+6.1f}%", f"{hd_s:>5}"]))
            rows_s = sorted(calc2, key=lambda r: r[5], reverse=True)
            if rows_s:
                lines.append("    涨幅榜: " + "  ".join(f"{n} {p:+.1f}%" for _, n, _, _, _, p, _ in rows_s[:3]))
            if losses:
                lines.append("    跌幅榜: " + "  ".join(f"{n} {p:+.1f}%" for _, n, _, _, _, p, _ in sorted(losses, key=lambda r: r[5])[:3]))
            # —— 深度：行业分布 / 今日贡献 / 风控距离（2026-08-06）——
            try:
                ind_w, ind_c = {}, {}
                for code, shares, ac, close, p, bd in pnl_rows:
                    ind = (sb.get(code) or ('', '', ''))[2] or '其他'
                    ind_w[ind] = ind_w.get(ind, 0) + shares * close
                    ind_c[ind] = ind_c.get(ind, 0) + 1
                tot_v = sum(ind_w.values())
                if tot_v > 0:
                    top_ind = sorted(ind_w.items(), key=lambda x: -x[1])[:5]
                    s = "  行业分布: " + "  ".join(f"{n} {v/tot_v*100:.0f}%/{ind_c[n]}只" for n, v in top_ind)
                    if top_ind and top_ind[0][1] / tot_v > 0.35:
                        s += " ⚠️集中"
                    lines.append(s)
            except Exception:
                pass
            try:
                contrib = []
                for code, shares, ac, close, p, bd in pnl_rows:
                    tc = ts_code(code)
                    r0 = tushare.execute("SELECT close FROM daily WHERE trade_date=? AND ts_code=?", (prev_td0, tc)).fetchone()
                    if r0 and r0[0] and float(r0[0]) > 0:
                        chg = close / float(r0[0]) - 1
                        contrib.append((code, shares * float(r0[0]) * chg, chg * 100))
                if contrib:
                    contrib.sort(key=lambda x: -x[1])
                    nm_of = lambda c: (sb.get(c) or (c, '', ''))[0]
                    lines.append("  今日贡献: " + "  ".join(f"{nm_of(c)} {v:+,.0f}元({g:+.1f}%)" for c, v, g in contrib[:3]))
                    neg3 = contrib[-3:]
                    if neg3 and neg3[0][1] < 0:
                        lines.append("  今日拖累: " + "  ".join(f"{nm_of(c)} {v:+,.0f}元({g:+.1f}%)" for c, v, g in neg3))
            except Exception:
                pass
            try:
                # 当日大盘（000001.SH 上证，与执行端 R3 回撤止盈大盘开关同口径；
                # 2026-09-02 修复：原"已破线未卖"未带大盘≤-2% 条件 → 高凌信息 9/1/9/2 连续误报，
                # 实际执行端 R3 需当日大盘≤-2%（2026-08-20 用户拍板）才触发，大盘未达标=规则内等待）
                mkt_entry = idx_map.get('000001.SH') or idx_map.get('000001')
                mkt_pct = float(mkt_entry[1]) if mkt_entry and mkt_entry[1] is not None else None
                peaks = {r[0]: float(r[1]) for r in state.execute("SELECT code, peak_price FROM led.position_peaks").fetchall()}
                # 当日分钟线（tdx_archive.min1_archive，16:10 已归档；盘后报告 23:00 可读）：
                # 用于复刻执行端 R4 触发语义（开盘破位立即卖 / 盘中破线 14:30 尾盘确认卖）。
                # 2026-09-08 修复（与 M2 同步）：此前直接用 led.holdings.stop_loss 判收盘破线，
                # 未同步 8/31 的 stop_eff=min(止损线,成本×0.94) 与尾盘确认语义 → 9/7 法兰泰克/迪威尔误报
                intraday_map = {}
                try:
                    codes_in = [r[0] for r in pnl_rows]
                    if codes_in:
                        ph = ','.join('?' * len(codes_in))
                        tdx = duckdb.connect(str(BASE / 'tdx_archive.db'), read_only=True)
                        _b = {}
                        for r in tdx.execute(
                                f"SELECT code, tm, open, low FROM min1_archive WHERE date=? AND code IN ({ph})",
                                [last_td] + codes_in).fetchall():
                            _b.setdefault(r[0], []).append(r)
                        for c, arr in _b.items():
                            arr.sort(key=lambda x: x[1])
                            op = arr[0][2]
                            lo_day = min(x[3] for x in arr) if arr else None
                            tail = [x for x in arr if x[1] >= 870]  # 14:30 起（执行端 STOP_CONFIRM_TIME）
                            lo_tail = min(x[3] for x in tail) if tail else None
                            intraday_map[c] = (op, lo_day, lo_tail)
                except Exception:
                    intraday_map = {}
                risks = []
                tp_pending = []  # 回撤止盈破线但大盘未达 -2%（R3 未触发，非漏卖）
                sl_pending = []  # 止损盘中破线但尾盘收回（R4 尾盘确认未过，规则内假摔，非漏卖）
                hit_sl = []      # 真缺口：止损开盘破位 / 止损尾盘破线 / 止盈线破线（大盘达标）
                today_s = f"{str(last_td)[:4]}-{str(last_td)[4:6]}-{str(last_td)[6:]}"
                for code, shares, ac, close, p, bd in pnl_rows:
                    nm = name_map.get(code, code)
                    slv = state.execute("SELECT stop_loss FROM led.holdings WHERE code=? AND status='hold'", (code,)).fetchone()
                    sl = float(slv[0] or 0) if slv else 0
                    # R4 止损价口径（2026-08-31 执行端）：min(持仓止损线, 成本×0.94)——止损永不比成本 -6% 更紧；
                    # 止损线缺失时执行端 R4 不触发（仅 -12%/-9% 无条件硬止损兜底），此处同样不判缺口
                    sl_eff = min(sl, ac * 0.94) if (sl and sl > 0 and ac and ac > 0) else 0.0
                    md = intraday_map.get(code)
                    if sl_eff > 0:
                        d_close = (close / sl_eff - 1) * 100
                        if bd and bd[:10] == today_s:
                            risks.append((d_close, code, nm, '止损'))  # 当日买入 T+1 卖不掉（执行端同规则），仅报距离
                        elif md is None:
                            risks.append((d_close, code, nm, '止损'))  # 分钟数据缺失（停牌/归档失败），收盘价报距离不判缺口
                        else:
                            open_p, lo_day, lo_tail = md
                            if open_p > 0 and open_p <= sl_eff:
                                hit_sl.append((code, nm, '止损开盘破位'))   # 开盘即在线下 → 9:30 应立即卖
                            elif lo_tail is not None and lo_tail <= sl_eff:
                                hit_sl.append((code, nm, '止损尾盘破线'))   # 14:30 后仍破线 → 尾盘确认该卖
                            elif lo_day is not None and lo_day <= sl_eff:
                                sl_pending.append((code, nm, d_close))      # 盘中破线但 14:30 后收回 → 规则内假摔
                            else:
                                risks.append((d_close, code, nm, '止损'))
                    pk = peaks.get(code)
                    if pk and ac and ac > 0 and pk >= 1.05 * ac:
                        line = pk * 0.92
                        d = (close / line - 1) * 100
                        if d <= 0:
                            # R3: 需当日大盘 ≤ -2%（2026-08-20 用户拍板）才触发回撤止盈
                            if mkt_pct is not None and mkt_pct <= -2.0:
                                hit_sl.append((code, nm, '止盈线破线'))  # 大盘达标仍破线 → 真该卖未卖
                            else:
                                tp_pending.append((code, nm, d))  # 大盘未达标 → 待触发
                        else:
                            risks.append((d, code, nm, '止盈线'))  # 未破线，仍报距离
                if risks:
                    risks.sort()
                    near = [r for r in risks if 0 < r[0] < 8]
                    if near:
                        lines.append("  ⚠️ 风控临近: " + "  ".join(f"{nm} 距{kind} {d:+.1f}%" for d, c, nm, kind in near[:4]))
                if hit_sl:
                    lines.append("  🚨 已破线未卖: " + "  ".join(f"{nm}({lb})" for code, nm, lb in hit_sl[:4]))
                pend_items = []
                if tp_pending:
                    mkt_s = f"{mkt_pct:+.1f}%" if mkt_pct is not None else "大盘数据缺失"
                    pend_items.append("回撤止盈待触发(需大盘≤-2%,现" + mkt_s + "): " +
                                      "  ".join(f"{nm}" for code, nm, d in tp_pending[:4]))
                if sl_pending:
                    pend_items.append("止损盘中破线尾盘收回(规则内假摔): " +
                                      "  ".join(f"{nm}" for code, nm, d in sl_pending[:4]))
                if pend_items:
                    for pi in pend_items:
                        lines.append("  ⏳ " + pi)
            except Exception:
                pass
    # —— 深度：持仓 × 最新信号联动（2026-08-07，与 intraday_decision 规则5同口径）——
    try:
        sig_rows = {}
        for r in state.execute(
            "SELECT stock_code, final_score, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=?",
            (d3,)).fetchall():
            sig_rows[str(r[0]).split('.')[0]] = (r[1], r[2])
        sell_cand, no_sig = [], []
        for code, shares, ac, close, p, bd in pnl_rows:
            sig = sig_rows.get(str(code).split('.')[0])
            if not sig:
                no_sig.append(code)
                continue
            fs, fus = sig
            if fs is None:
                continue
            hold_d = holding_days(bd)
            # 规则5A: 评分>0 且 <55 且浮亏 → 明日盘中可能触发"评分转负"卖出
            if 0 < fs < 55 and p < 0:
                sell_cand.append((fs, code, name_map.get(code, code), '评分转负'))
            # 规则5B（2026-08-18 用户拍板阈值8%）：持仓≥20天 且 评分<30 且 盈亏<8% → 超期低分横盘卖出
            # ⚠️ 原条件 0<fs<30 排除负分持仓（评分越差反而躲过卖出）→ 已去掉，负分同样触发；
            #    盈亏<8% 防误杀盈利持仓（8/18 实况：24只全盈利但22只评分<30，纯评分阈值会全仓误杀）
            elif hold_d is not None and hold_d >= 20 and fs < 30 and p < 8.0:
                sell_cand.append((fs, code, name_map.get(code, code), '超期低分'))
            # 规则5C（2026-09-15 用户拍板）：持仓≥30交易日 且 融合分fusion<0 → 无条件清仓（盈亏豁免不适用），
            #   与 intraday_decision.py RULE5C_HOLD_DAYS 同口径；fusion 为 None 不误判
            elif fus is not None and hold_d is not None and hold_d >= 30 and fus < 0:
                sell_cand.append((fs, code, name_map.get(code, code), f'5C融合转负{fus:.1f}'))
        if sell_cand:
            lines.append("  🚨 卖出候选(明日盘中可能触发): " + "  ".join(
                f"{nm}({kind} {fs:.0f})" for fs, c, nm, kind in sorted(sell_cand, key=lambda x: x[0])))
        if no_sig:
            lines.append("  ⚠️ 无最新日评分: " + "  ".join(no_sig))
    except Exception:
        pass
    sa_rows = state.execute(
        "SELECT account_id, date, nav, daily_ret, market_ret FROM led.strategy_accounts "
        "WHERE date=(SELECT MAX(date) FROM led.strategy_accounts) ORDER BY account_id").fetchall()
    # 2026-08-31 用户拍板：报告剔除三因子融合/三因子+三模型（账户照跑，只是不进报告）
    _EXCLUDED_IN_REPORT = {'fusion3f', 'fusion_dual'}  # 2026-09-11 CMMR 停推；2026-09-17 用户拍板恢复 cmmr/cmmr_fusion 进报告
    sa_rows = [r for r in sa_rows if r[0] not in _EXCLUDED_IN_REPORT]
    if sa_rows:
        lines.append("  策略账户（模拟）:")
        for aid, dt, nav, dr, mr in sa_rows:
            name = STRATEGY_NAMES.get(aid, aid)
            cum = (nav/INIT_CAPITAL - 1) * 100
            ex = None
            try:
                # 2026-09-17 用户拍板：基准改用 tushare.db 中证1000 官方收盘价序列
                # （账本 market_ret 是记账时点的盘中瞬时值，8/4 曾低记 2.5pp 把超额吹高 3pp+）
                _first = state.execute(
                    "SELECT MIN(date) FROM led.strategy_accounts WHERE account_id=?", (aid,)).fetchone()[0]
                ex = cum - _index_bench_pct(dt, _first)
            except Exception:
                pass
            ex_s = f"  超额 {ex:+.2f}%" if ex is not None else ""
            lines.append(f"    {name}: NAV {nav:,.0f}  当日收益 {dr:+.2f}%（NAV总资产口径）  累计 {cum:+.2f}%{ex_s}  (市场 {mr:+.2f}%)")
            # 策略账户持仓表格（2026-08-05：从 sim_accounts json 读取）
            try:
                acct_f = BASE / 'sim_accounts' / f'{aid}.json'
                if not acct_f.exists():
                    continue
                acct = json.load(open(acct_f))
                poss = acct.get('positions', [])
                if not poss:
                    lines.append("    （空仓）")
                    continue
                # 用 tushare 收盘价补现价（策略账户 json 里只有成本/股数）
                code_map = {}
                for p in poss:
                    tc = ts_code(p['code'])
                    r = tushare.execute(
                        "SELECT close FROM daily WHERE trade_date=? AND ts_code=?",
                        (last_td, tc)).fetchone()
                    code_map[p['code']] = float(r[0]) if r and r[0] else (p.get('peak_price') or p['avg_cost'])
                lines.append("    " + "  ".join([
                    f"{'代码':<6}", f"{'名称':<8}", f"{'股数':>8}", f"{'成本':>8}", f"{'现价':>8}", f"{'盈亏%':>7}", f"{'持仓':>5}"]))
                for p in sorted(poss, key=lambda x: x.get('avg_cost', 0)):
                    px = code_map.get(p['code'], p.get('avg_cost', 0))
                    pnl = (px / p['avg_cost'] - 1) * 100 if p.get('avg_cost') else 0
                    hd = holding_days(p.get('buy_date'))
                    hd_s = f"{hd}天" if hd is not None else "-"
                    lines.append("    " + "  ".join([
                        f"{p['code']:<6}", f"{str(p.get('name','')):<8}", f"{p['shares']:>8,}",
                        f"{p['avg_cost']:>8.2f}", f"{px:>8.2f}", f"{pnl:>+6.1f}%", f"{hd_s:>5}"]))
                # 深度：距止损预警（2026-08-06）
                try:
                    warns = []
                    for p in poss:
                        sl = p.get('stop_loss') or 0
                        px = code_map.get(p['code'])
                        if sl and px:
                            d = (px / sl - 1) * 100
                            if d < 6:
                                warns.append((d, str(p.get('name', '')), p['code']))
                    if warns:
                        warns.sort()
                        lines.append("    ⚠️ 距止损<6%: " + "  ".join(f"{n} {d:+.1f}%" for d, n, c in warns[:3]))
                except Exception:
                    pass
            except Exception:
                pass
    lines.append("")

    # ═══ ③ 评分 Top10 ═══
    lines.append(f"【评分 Top10】（信号日 {d3}）")
    lines.append("  三模型融合:")
    rows = state.execute("""
        SELECT stock_code, stock_name, ROUND(fusion_score,2), industry FROM signal_history
        WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
        ORDER BY fusion_score DESC LIMIT 50
    """, (d3,)).fetchall()
    added = 0
    for r in rows:
        if is_bad(sb, r[0]):
            continue
        lines.append(f"    {added+1}. {r[0]} {r[1]} 融合分{r[2]} ({r[3]})")
        added += 1
        if added >= 10:
            break
    # 2026-08-31 用户拍板：三因子融合榜单剔除（与账户区口径一致，信号链照跑不进报告）
    # lines.append("  三因子融合:")  ... 原 fusion_3f_signals 强买 top10 段，注释停用
    # 2026-09-11 用户拍板：CMMR独立 / CMMR+三模型融合 两榜停止在报告中输出（原始数据仍在 signal_history）
    # 2026-09-17 用户拍板：恢复两榜（与策略账户 cmmr / cmmr_fusion 同源同口径）
    lines.append("  CMMR独立:")
    try:
        rows = state.execute("""
            SELECT stock_code, stock_name, ROUND(cmmr_score,2) FROM signal_history
            WHERE REPLACE(date,'-','')=? AND cmmr_score > 0
            ORDER BY cmmr_score DESC LIMIT 50
        """, (d3,)).fetchall()
        added = 0
        for r in rows:
            if is_bad(sb, r[0]):
                continue
            lines.append(f"    {added+1}. {r[0]} {r[1]} CMMR分{r[2]}")
            added += 1
            if added >= 10:
                break
    except Exception:
        lines.append("    （该榜计算失败，跳过）")
    lines.append("  CMMR+三模型融合:")
    try:
        rows = state.execute("""
            SELECT stock_code, stock_name, ROUND(fusion_score_cmmr,2), cmmr_score, ROUND(ma40_slope,4)
            FROM signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score_cmmr IS NOT NULL AND fusion_score_cmmr > 0
            ORDER BY fusion_score_cmmr DESC LIMIT 50
        """, (d3,)).fetchall()
        added = 0
        for r in rows:
            if is_bad(sb, r[0]):
                continue
            lines.append(f"    {added+1}. {r[0]} {r[1]} 融合分{r[2]} CMMR={r[3]:.0f} 斜率{r[4]:+.4f}")
            added += 1
            if added >= 10:
                break
    except Exception:
        lines.append("    （该榜计算失败，跳过）")
    # 10d独立榜（2026-09-11 用户拍板新建：reg10 v3 预测单独排序 top10。
    # 背景：fusion_score 里 reg10 因小数口径直接线性、实际贡献≈0.08%，融合排序近乎不含10d；
    # 网格测试(09-10, 35成熟日)显示提 reg10 权单调有增益。此榜观察 10d 独立排序质量，
    # 与 442-v3 影子腿并跑，10 月中旬 NW-t 终判后再决定是否进融合。
    # reg10=十进制小数(0.086=+8.6%)，展示时×100 化百分点；★=同时在 fusion 全市场前10）
    lines.append("  10d独立:")
    try:
        _r10 = state.execute("""
            SELECT stock_code, stock_name, reg10 FROM signal_history
            WHERE REPLACE(date,'-','')=? AND reg10 IS NOT NULL
            ORDER BY reg10 DESC LIMIT 50
        """, (d3,)).fetchall()
        _fus_top10 = {r[0] for r in state.execute("""
            SELECT stock_code FROM signal_history
            WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL
            ORDER BY fusion_score DESC LIMIT 10
        """, (d3,)).fetchall()}
        added = 0
        for r in _r10:
            if is_bad(sb, r[0]):
                continue
            star = '★' if r[0] in _fus_top10 else ''
            lines.append(f"    {added+1}. {star}{r[0]} {r[1] or ''} 10d预测{r[2]*100:+.1f}%")
            added += 1
            if added >= 10:
                break
    except Exception:
        lines.append("    （该榜计算失败，跳过）")
    lines.append( "")
    # 信号分布（2026-09-04 用户拍板：三因子系已证伪，fusion_3f 信号分布移出报告）
    # try:
    #     dist = state.execute(
    #         "SELECT signal, COUNT(*) FROM fusion_3f_signals WHERE REPLACE(date,'-','')=? GROUP BY 1", (d3,)).fetchall()
    #     dmap = {r[0]: r[1] for r in dist}
    #     lines.append(f"  (信号分布: 强买{dmap.get('强买',0)}/买{dmap.get('买',0)}/持{dmap.get('持',0)}/卖{dmap.get('卖',0)}/强卖{dmap.get('强卖',0)})")
    # except Exception:
    #     pass
    # 中枢版观察名单（2026-08-06：中枢版融合 强买 top10，三因子倒U信息中枢化，
    # 17年样本外 IC +0.060 t=+37；与策略账户 fusion_center 信号源同口径）
    lines.append("  中枢版:")
    rows = state.execute("""
        SELECT stock_code, stock_name, score, rank_pct FROM fusion_center_signals
        WHERE REPLACE(date,'-','')=? AND signal='强买'
        ORDER BY score DESC LIMIT 50
    """, (d3,)).fetchall()
    added = 0
    for r in rows:
        if is_bad(sb, r[0]):
            continue
        nm = r[1] or (sb.get(r[0], ('', '', ''))[0] or '')
        lines.append(f"    {added+1}. {r[0]} {nm} 中枢分{r[2]:.3f} 百分位{r[3]*100:.1f}%")
        added += 1
        if added >= 10:
            break
    # 中枢版+三模型 融合榜（2026-09-04 补榜：与策略账户 center_dual 同口径——
    # 0.5*pct(中枢score)+0.5*pct(fusion_score) 横截面百分位等权，取交集排序 top10）
    lines.append("  中枢版+三模型:")
    try:
        _ct = {r[0]: float(r[1]) for r in state.execute(
            "SELECT stock_code, score FROM fusion_center_signals WHERE REPLACE(date,'-','')=? AND score IS NOT NULL", (d3,)).fetchall()}
        _md = {r[0]: float(r[1]) for r in state.execute(
            "SELECT stock_code, fusion_score FROM signal_history WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL", (d3,)).fetchall()}
        _common = sorted(set(_ct) & set(_md))
        if _common:
            _n = len(_common)
            _ctr = {c: (i + 1) / _n * 100 for i, c in enumerate(sorted(_common, key=lambda c: _ct[c]))}
            _mdr = {c: (i + 1) / _n * 100 for i, c in enumerate(sorted(_common, key=lambda c: _md[c]))}
            _comb = sorted(((c, 0.5 * _ctr[c] + 0.5 * _mdr[c]) for c in _common), key=lambda x: x[1], reverse=True)
            added = 0
            for c, s in _comb:
                if is_bad(sb, c):
                    continue
                nm = sb.get(c, ('', '', ''))[0] or ''
                lines.append(f"    {added+1}. {c} {nm} 综合分{s:.1f}")
                added += 1
                if added >= 10:
                    break
    except Exception:
        lines.append("    （该榜计算失败，跳过）")
    lines.append("")

    # ═══ ③a 尾盘异动预警（2026-08-08 TDX 分钟数据新增；2026-09-11 抽成 tail_alerts() 并显式排序）═══
    lines.extend(tail_alerts(state, sb, d3))

    # ═══ ③b 信号验证（2026-08-06 深度版）═══
    lines.append("【信号验证】")
    # 滚动5信号日：三模型 Top10 次日超额（2026-08-07 深度版，替代原单日验证）
    try:
        sig_dates = [r[0] for r in state.execute(
            "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history WHERE fusion_score IS NOT NULL "
            "ORDER BY 1 DESC LIMIT 6").fetchall()]
        ex_list = []
        for sd in sig_dates[1:]:
            rows = state.execute(
                "SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL "
                "ORDER BY fusion_score DESC LIMIT 50", (sd,)).fetchall()
            codes = []
            for r in rows:
                if not is_bad(sb, r[0]):
                    codes.append(r[0])
                if len(codes) >= 10:
                    break
            if not codes:
                continue
            nxt = tushare.execute("SELECT MIN(trade_date) FROM daily WHERE trade_date > ?", (sd,)).fetchone()[0]
            if not nxt:
                continue
            ts_codes = [ts_code(c) for c in codes]
            ph = ','.join(['?'] * len(ts_codes))
            map_ret = {r[0]: r[1] for r in tushare.execute(
                f"SELECT ts_code, pct_chg FROM daily WHERE trade_date=? AND ts_code IN ({ph})",
                (nxt,) + tuple(ts_codes)).fetchall()}
            rets = [map_ret[tc] for tc in ts_codes if tc in map_ret]
            mkt = tushare.execute("SELECT AVG(pct_chg) FROM daily WHERE trade_date=?", (nxt,)).fetchone()[0]
            if rets and mkt is not None:
                ex_list.append((sd, sum(rets) / len(rets) - mkt))
        if ex_list:
            avg_ex = sum(e for _, e in ex_list) / len(ex_list)
            win = sum(1 for _, e in ex_list if e > 0)
            lines.append("  三模型Top10次日超额(近5信号日): " + "  ".join(
                f"{sd[4:]}{e:+.1f}" for sd, e in ex_list) + f"  均 {avg_ex:+.2f}% 正 {win}/{len(ex_list)}")
    except Exception:
        pass
    try:
        ic5 = state.execute("""SELECT AVG(ic_fusion), AVG(ic_reg10), AVG(ic_reg20), AVG(ic_reg40)
            FROM (SELECT * FROM ic_daily ORDER BY signal_date DESC LIMIT 5)""").fetchone()
        if ic5 and ic5[0] is not None:
            lines.append("  模型IC近5日均值: " + "  ".join(
                f"{l} {v:+.2f}" for l, v in [('融合', ic5[0]), ('10d', ic5[1]), ('20d', ic5[2]), ('40d', ic5[3])]))
    except Exception:
        pass
    # 三因子强买次日超额（2026-09-04 用户拍板：三因子系已证伪，移出报告统计）
    # try:
    #     bt5 = state.execute("SELECT signal_date, sb_ew, mkt_ew FROM fusion_3f_backtest ORDER BY signal_date DESC LIMIT 5").fetchall()
    #     pairs = [(r[0], r[1], r[2]) for r in bt5 if r[1] is not None and r[2] is not None]
    #     if pairs:
    #         exs = [sb - mk for _, sb, mk in pairs]
    #         lines.append("  三因子强买次日超额(近5): " + "  ".join(
    #             f"{sd[4:]}{sb-mk:+.1f}" for sd, sb, mk in pairs) +
    #             f"  均 {sum(exs)/len(exs):+.2f}% 正 {sum(1 for e in exs if e>0)}/{len(exs)}")
    # except Exception:
    #     pass
    # 2026-09-11 CMMR/CMMR+ 次日超额段已移除（用户拍板停推）；2026-09-17 用户拍板恢复
    try:
        cbt5 = state.execute("SELECT signal_date, cmmr_ew, cmmr80_ew, fsc_ew FROM cmmr_backtest ORDER BY signal_date DESC LIMIT 5").fetchall()
        if cbt5:
            c0 = cbt5[0]
            lines.append(f"  CMMR最新({c0[0]}): 等权 {c0[1]:+.2f}% | 高分80+ {c0[2]:+.2f}% | CMMR+ {c0[3]:+.2f}%")
            pairs2 = [(r[0], r[1], r[3]) for r in cbt5 if r[1] is not None and r[3] is not None]
            if pairs2:
                exs2 = [c - f for _, c, f in pairs2]
                lines.append("  CMMR/CMMR+次日超额(近5): " + "  ".join(
                    f"{sd[4:]}{c-f:+.1f}" for sd, c, f in pairs2) +
                    f"  均 {sum(exs2)/len(exs2):+.2f}% 正 {sum(1 for e in exs2 if e>0)}/{len(exs2)}")
    except Exception:
        pass
    lines.append("")

    # ═══ ④ 明日策略 ═══
    lines.append("【明日策略】")
    if _RE_IMPORT_ERR:
        lines.append(f"  ⚠️ 重评窗口配置读取失败（{_RE_IMPORT_ERR}）→ 窗口按默认 {REBALANCE_INTERVAL} 日显示")
    for aid in ['fusion_center', 'center_dual', 'reg10_solo', 'cmmr', 'cmmr_fusion', 'cmmr_clf']:  # 2026-08-31 剔除 fusion3f/fusion_dual；2026-09-11 剔除 cmmr/cmmr_fusion；2026-09-15 增 reg10_solo；2026-09-17 恢复 cmmr 两户；2026-09-21 增 cmmr_clf 验证账户（未建仓时自动显示"待首次建仓"）
        try:
            acct_f = BASE / 'sim_accounts' / f'{aid}.json'
            if not acct_f.exists():
                continue
            acct = json.load(open(acct_f))
            last_re = str(acct.get('config', {}).get('last_rebalance_date') or '')
            if last_re:
                n = tushare.execute(
                    "SELECT COUNT(DISTINCT trade_date) FROM daily WHERE trade_date > ? AND trade_date <= ?",
                    (last_re.replace('-', ''), last_td)).fetchone()[0]
                name = STRATEGY_NAMES[aid]
                # per-account 重评窗口：单一来源 ACCOUNTS（2026-09-11 去硬编码；中枢版/中枢+三模型=20）
                _re = _STRAT_ACCOUNTS.get(aid, {}).get('rebalance', REBALANCE_INTERVAL)
                remain = max(0, _re - 1 - int(n or 0))
                if remain == 0:
                    lines.append(f"  {name}: 明日为重评日（按最新信号 top10 整仓重建）")
                else:
                    lines.append(f"  {name}: 距重评还有 {remain} 个交易日（窗口内仅止损止盈）")
            else:
                # 新账户未建仓（2026-08-06 中枢版）
                lines.append(f"  {STRATEGY_NAMES.get(aid, aid)}: 待首次建仓（开盘自动按最新信号 top10 建仓）")
        except Exception:
            continue
    # agent_auto：manual 账户，不参与自动重评（2026-09-04）
    lines.append("  Agent全权: agent自主择时（9:45/13:15/14:35 三次盘中决策，manual不自动重评）")
    wl = state.execute(
        "SELECT COUNT(*) FROM led.watchlist WHERE REPLACE(scan_date,'-','')=?", (d3,)).fetchone()[0]
    lines.append(f"  主账户: watchlist 观察 {wl} 只（最新信号日 {d3}）")
    # 深度：watchlist 非持仓 top5 重点观察（2026-08-06）
    try:
        hold_codes = set(r[0] for r in state.execute("SELECT code FROM led.holdings WHERE status='hold'").fetchall())
        wl_rows = state.execute("""SELECT ts_code, score FROM led.watchlist
            WHERE REPLACE(scan_date,'-','')=? ORDER BY score DESC LIMIT 20""", (d3,)).fetchall()
        obs = []
        for tc, sc in wl_rows:
            code = str(tc).split('.')[0]
            if code in hold_codes:
                continue
            nm = (sb.get(code) or (code, '', ''))[0]
            obs.append(f"{nm}({sc:.1f})")
            if len(obs) >= 5:
                break
        if obs:
            lines.append("  重点观察: " + "  ".join(obs))
    except Exception:
        pass
    try:
        def _mkt_state(ts_code):
            rows = tushare.execute(
                "SELECT close FROM index_daily_raw WHERE ts_code=? ORDER BY trade_date", (ts_code,)).fetchall()
            closes = [float(r[0]) for r in rows]
            if len(closes) < 15:
                return None
            # 2026-08-06 用户要求逐级缩短：40日 → MA20 vs 10日前 → MA10 vs 5日前。
            # 数据验证（60日样本）：MA10 vs 5日前 std=1.14/3.19（上证/中证1000）、0线穿越 3次/60日，
            # 拐点响应最快且不跳变；MA5 vs 5日前 穿越 5次 噪声过大弃用。
            ma10 = sum(closes[-10:]) / 10
            ma10p = sum(closes[-15:-5]) / 10
            slope = (ma10 - ma10p) / ma10p * 100
            mkt = '上升趋势' if slope > 0.5 else ('震荡' if slope > -0.3 else '下跌趋势')
            return f"{mkt}（MA10斜率 {slope:+.2f}%）"
        st_sh = _mkt_state('000001.SH')
        st_zz = _mkt_state('000852.SH')
        # 2026-08-06 用户质疑"大盘一直下跌"：上证确实连跌（近20日斜率全负），
        # 但中证1000 前期跌更狠(-13.9%)且近5日反弹更强——单看上证会误导（策略账户基准是中证1000），
        # 改双指数显示；MA20斜率为40日滞后指标，近5日反弹尚未反映
        if st_sh and st_zz:
            lines.append(f"  大盘状态: 上证 {st_sh} | 中证1000 {st_zz}")
        elif st_sh:
            lines.append(f"  大盘状态: {st_sh}")
    except Exception:
        pass
    lines.append("")

    # ═══ ⑤ 系统流程检查 ═══
    lines.append("【系统流程检查】")
    # 5a. 数据新鲜度
    lines.append("  数据新鲜度:")
    checks = [
        ('daily 行情', last_td),
        ('signal_history', d3),
        # 2026-09-04 用户拍板：fusion_3f 新鲜度移出报告（三因子系已证伪）
    ]
    for name, v in checks:
        ok = (v == last_td)
        mark = '✅' if ok else '⚠️'
        if not ok:
            issues.append(f"{name}最新日 {v} ≠ 交易日 {last_td}")
        lines.append(f"    {mark} {name}: {v}")
    # ic 类：模型IC/ETF IC 需次日收益，最新=上一交易日是正常（滞后一天设计）
    ic_d = str(state.execute("SELECT MAX(signal_date) FROM ic_daily").fetchone()[0] or '').replace('-', '')
    etf_ic = str(state.execute("SELECT MAX(signal_date) FROM etf_ic").fetchone()[0] or '').replace('-', '')
    fr = str(state.execute("SELECT MAX(as_of_date) FROM factor_ic_roll").fetchone()[0] or '').replace('-', '')
    # 预期：d3 或 d3 前一个交易日（IC 滞后一天）
    prev_td = tushare.execute(
        "SELECT MAX(trade_date) FROM daily WHERE trade_date < ?", (last_td,)).fetchone()[0]
    for name, v in [('模型IC', ic_d), ('因子IC滚动', fr), ('ETF IC', etf_ic)]:
        ok = (v in (d3, str(prev_td).replace('-', '')))
        mark = '✅' if ok else '⚠️'
        if not ok:
            issues.append(f"{name}最新 {v}（预期 {d3} 或 {prev_td}）")
        lines.append(f"    {mark} {name}: {v}")
    # 5b. 每日链 cron 状态（按最新交易日核对，报告可能在次日凌晨跑）
    lines.append("  每日链 cron:")
    cron_lines = check_cron_chain(last_td)
    lines.extend(cron_lines)
    for cl in cron_lines:
        if '❌' in cl or '⚠️' in cl:
            issues.append(cl.strip())
    # 5c. health_verify 8 链
    hv_out, hv_fails, hv_ok = run_health_verify()
    if hv_ok:
        lines.append(f"  ✅ 全链路健康检查: 通过")
    else:
        lines.append(f"  ❌ 全链路健康检查: 异常 {len(hv_fails)} 项")
        for f_ in hv_fails[:5]:
            lines.append(f"    {f_}")
            issues.append(f_)

    state.close()
    tushare.close()

    # 异常置顶
    if issues:
        head = ["⚠️ " + " | ".join(dict.fromkeys(issues))[:200]]
        lines = head + [""] + lines

    msg = '\n'.join(lines)
    # QQ 单条消息上限 4000 字符——报告超长时分段推送（2026-08-06 修复：
    # 6573 字符被截断在 4000，Top10/明日策略/系统检查全丢）
    chunks = []
    cur = ''
    for line in msg.split('\n'):
        if len(cur) + len(line) + 1 > 3800 and cur:  # 留余量
            chunks.append(cur)
            cur = line
        else:
            cur = (cur + '\n' + line) if cur else line
    if cur:
        chunks.append(cur)
    # 三 bot 推送：主 bot + 小rayray + qqbot3（2026-08-13）
    # 09-02 默认改为 dry：推送必须显式 --push（防止手动验证误推；23:55综合报告由cron agent自己组织推送）
    if '--push' not in sys.argv:
        print(f'===== DRY RUN: 不推送（共 {len(chunks)} 段 / {len(msg)} 字符）；需要推送加 --push =====')
        print(msg)
        return
    active = [t for t in QQ_TARGETS if 'PENDING_OPENID' not in t]
    for target in active:
        for chunk in chunks:
            r = subprocess.run(['hermes', 'send', '-t', target, chunk],
                               capture_output=True, timeout=60)
            if r.returncode != 0:
                print(f'❌ 推送失败({target}): {r.stderr.decode()[:200]}')
                sys.exit(1)
    print(f'✅ 每日盘后报告已推送 QQ × {len(active)} ({today}) 共 {len(chunks)} 段')
    print(msg)

if __name__ == '__main__':
    main()
