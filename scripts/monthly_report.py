#!/usr/bin/env python3
"""Mac 原生月报 v2（2026-10-01 深度化改造；v1=09-28 自建，.bak.20261001_v1）。

架构（10-01 用户拍板："月报太简陋，要深度分析，用 LLM 模式写"）：
  本脚本 = 确定性深度底稿（所有数字引擎算死，只读库）；
  cron 489b7d201800 = LLM 模式（no_agent=false），读本脚本 stdout 底稿 +
  二次取数复盘后撰写分析正文（与每日综合报告 ee38c4107fbe 同架构）。
  ⇒ 本脚本输出的数字是唯一事实源，LLM 禁止重算/禁止另取数改写数值。

v1 口径（保留）：
  ①主账户月况: 月流水、月内已实现盈亏(均价法近似)、当前 NAV/持仓快照。
  ②策略账户月况: strategy 逐个买入/卖出笔数与金额（一律 amount，禁 qty×price）。
  ③成交质量哨兵: 全库量金不符笔数（>1%）。——月报是"每日防线的月度复盘"。
  ④信号链月况: ic_daily/fusion_ic_daily/cmmr_ic_daily 月均 RankIC。
v2 新增（全部确定性计算，供 LLM 解读，不许 LLM 自己算）：
  ⑤市场环境: index_daily_raw 三大指数 月收益/上涨天数/月内最大回撤/日波动(年化)。
  ⑥逐账户深度量化: 日均超额序列 t 值（mu/sd*sqrt(n)）、超额为正天数、
     最大回撤区间(峰日→谷底日→修复日/月末未修复)、月换手=(买额+卖额)/日均NAV、
     逐票严格 FIFO 月内已实现盈亏(贡献top/拖累top)、平仓笔 FIFO 数量加权
     平均持有天数（对照策略重评窗口判过度交易）。
  ⑦IC 显著性: 月均 IC + IC>0 天数 + t 值（|t|<2 标"未达显著"——用户统计纪律）。

推送: hermes send -t qqbot（默认打印，--push 才推，与 daily_report 同纪律；
  LLM 月报链路 cron agent 最终回复由 job deliver 自动推送，脚本用默认打印）。
调度: cron 55 23 1 * *（每月1日 23:55 出上月账，避免 M2 那种 28-31 重复跑）。
cron 纪律: 解释器钉死 /usr/bin/python3；路径字面量全在本 .py（.sh 无 .db 字面量）。
"""
import argparse
import math
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LEDGER = BASE / "ledger.db"
SIGNALS = BASE / "signals.db"
TUSHARE = BASE / "tushare.db"
COMMISSION = 1.0003  # 主账户佣金口径（BUY ×1.0003 / SELL ÷已含）——与 daily_audit 一致


def _load_closed_accounts():
    """销户名单单一来源 = strategy_accounts_daily.py 的 ACCOUNTS['closed': True]
    （09-11 f3f/f_dual 销户留痕于此）。regex 解析，不 import（该脚本 import 有副作用）。
    解析失败回退硬编码名单，宁多滤不漏滤。"""
    import re
    src_path = BASE / "scripts" / "strategy_accounts_daily.py"
    try:
        txt = src_path.read_text(errors="ignore")
        closed = set(re.findall(
            r"'([a-z0-9_]+)':\s*\{[^{}]*'closed':\s*True", txt))
        if closed:
            return closed
    except Exception:
        pass
    return {"fusion3f", "fusion_dual"}


def month_str():
    """默认月: 当天所在月（调度在次月1日跑时用 --month 显式指上月；
    默认取当月防 9/29 手动触发算成 8 月账的指月偏移）。"""
    return date.today().strftime("%Y-%m")


def _tstat(vals):
    """日均序列显著性：返回 (mean, t, n, 正数天数)。t = mean/sd*sqrt(n)（sd 用
    样本标准差 n-1）。n<3 返回 None（样本不足，禁止由它下结论——用户统计纪律）。"""
    n = len(vals)
    if n < 3:
        return None
    mu = sum(vals) / n
    var = sum((x - mu) ** 2 for x in vals) / (n - 1)
    sd = math.sqrt(var)
    t = (mu / sd * math.sqrt(n)) if sd > 1e-12 else None
    return mu, t, n, sum(1 for x in vals if x > 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM，默认上月")
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()
    mon = args.month or month_str()
    m_start, m_end = f"{mon}-01", f"{mon}-31"  # LIKE 上界宽松取 <= 即可
    m_start_c, m_end_c = mon.replace("-", ""), mon.replace("-", "") + "31"

    L = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True)
    L.row_factory = sqlite3.Row
    out = [f"📊 A-Quant 月报 {mon}（MacBook 本机账本·深度底稿 v2）",
           "═" * 40]

    # ── ⑤ 市场环境（v2；DuckDB 只读，指数权威源=index_daily_raw，勿用滞后的 index_daily）──
    try:
        import duckdb
        D = duckdb.connect(str(TUSHARE), read_only=True)
        out.append("")
        out.append(f"【市场环境 {mon}】(index_daily_raw)")
        for code, nm in [("000001.SH", "上证"), ("000852.SH", "中证1000"),
                         ("399006.SZ", "创业板")]:
            rows = D.execute(
                "SELECT trade_date, pct_chg FROM index_daily_raw "
                "WHERE ts_code=? AND trade_date>=? AND trade_date<=? "
                "ORDER BY trade_date",
                (code, m_start_c, m_end_c)).fetchall()
            if len(rows) < 5:
                continue
            rets = [r[1] / 100 for r in rows]
            cum, peak, mdd = 1.0, 1.0, 0.0
            for x in rets:
                cum *= (1 + x)
                peak = max(peak, cum)
                if peak > 0:
                    mdd = min(mdd, cum / peak - 1)
            res = _tstat(rets)
            mu, t, n, up = res
            sd = math.sqrt(sum((x - mu) ** 2 for x in rets) / (n - 1))
            out.append(f"  {nm}({code}) 月收益 {100*(cum-1):+.2f}% ｜ "
                       f"上涨 {up}/{n} 天 ｜ 月内最大回撤 {mdd*100:.1f}% ｜ "
                       f"日波动(年化) {sd*math.sqrt(252)*100:.0f}%")
        D.close()
    except Exception as e:
        out.append(f"  ⚠️ 市场环境段异常: {type(e).__name__}: {e}")

    # ── ① 主账户 ──
    main_trades = L.execute(
        "SELECT direction, amount FROM trade_log WHERE strategy='main' "
        "AND trade_date>=? AND trade_date<=?", (m_start, m_end)).fetchall()
    buys = sum(r["amount"] for r in main_trades if r["direction"] == "BUY")
    sells = sum(r["amount"] for r in main_trades if r["direction"] == "SELL")
    # 月末引擎态（account_balance 只有当前行 → 报"截至最新"而非假装历史）
    acct = L.execute("SELECT cash_balance, total_value, last_update FROM account_balance").fetchone()
    hold_rows = L.execute(
        "SELECT code, name, shares, avg_cost, latest_price, pnl, pnl_pct FROM holdings "
        "ORDER BY pnl DESC").fetchall()
    mkt_value = sum(r["shares"] * (r["latest_price"] or r["avg_cost"]) for r in hold_rows)
    # 月内已实现盈亏（SELL 笔 notes 无 pnl → 均价成本 FIFO 近似，标注口径）
    realized = 0.0
    lots = {}  # code -> [shares, cost_sum]  (avg_cost 法近似，非严格逐笔FIFO)
    for r in L.execute(
            "SELECT code, direction, quantity, price, trade_date FROM trade_log "
            "WHERE strategy='main' AND trade_date<=? ORDER BY trade_date, trade_time", (m_end,)):
        if r["direction"] == "BUY":
            k = lots.setdefault(r["code"], [0, 0.0])
            k[0] += r["quantity"] or 0; k[1] += (r["quantity"] or 0) * (r["price"] or 0)
        else:
            k = lots.get(r["code"])
            if k and k[0] > 0:
                unit = k[1] / k[0]
                take = min(r["quantity"] or 0, k[0])
                realized += take * ((r["price"] or 0) - unit)
                k[0] -= take; k[1] -= take * unit
    last_up = str(acct["last_update"])[:10] if acct["last_update"] else "?"
    in_mon = m_start <= last_up <= m_end
    out.append("")
    out.append(f"【主账户 {mon}】")
    out.append(f"  买入 {len([r for r in main_trades if r['direction']=='BUY'])} 笔 "
               f"{buys:,.0f} 元 ／ 卖出 {len([r for r in main_trades if r['direction']=='SELL'])} 笔 "
               f"{sells:,.0f} 元")
    out.append(f"  月内已实现盈亏(均价法近似): {realized:+,.0f} 元")
    tag = "（最新快照，即月末态）" if in_mon else f"（快照日 {last_up}，非本月末）"
    out.append(f"  当前 NAV {acct['total_value']:,.2f} 元 现金 {acct['cash_balance']:,.2f} 元{tag}")
    if hold_rows:
        out.append(f"  持仓 {len(hold_rows)} 只 市值 {mkt_value:,.0f} 元"
                   f"（截至快照 {last_up}）:")
        for r in hold_rows[:12]:
            out.append(f"    {r['name']}({r['code']}) {r['shares']}股 成本{r['avg_cost']:.2f} "
                       f"现价{r['latest_price']:.2f} {r['pnl_pct']:+.2f}%")

    # ── ② 策略账户流水 ──
    out.append("")
    out.append(f"【策略账户 {mon}】(金额=amount 净额口径)")
    rows = L.execute(
        "SELECT strategy, direction, COUNT(*) n, SUM(amount) s FROM trade_log "
        "WHERE strategy!='main' AND strategy IS NOT NULL AND strategy!='' "
        "AND trade_date>=? AND trade_date<=? GROUP BY strategy, direction "
        "ORDER BY strategy", (m_start, m_end)).fetchall()
    agg = {}
    for r in rows:
        a = agg.setdefault(r["strategy"], {"bn": 0, "bs": 0.0, "sn": 0, "ss": 0.0})
        if r["direction"] == "BUY":
            a["bn"], a["bs"] = r["n"], r["s"] or 0
        else:
            a["sn"], a["ss"] = r["n"], r["s"] or 0
    for st, a in sorted(agg.items()):
        out.append(f"  {st:<16} 买{a['bn']:>3}笔 {a['bs']:>12,.0f}  卖{a['sn']:>3}笔 {a['ss']:>12,.0f}")

    # ── ⑥ 逐账户策略分析 + 深度量化（数字全部引擎算死，LLM 只许引用不许重算）──
    out.append("")
    out.append(f"【逐账户策略分析 {mon}】")
    try:
        meta = {r["account_id"]: r for r in L.execute(
            "SELECT * FROM strategy_accounts_meta")}
        # 销户口径与交易侧/日报对齐（09-11 f3f/f_dual 销户 closed=True，NAV 止于
        # 20260910/16；daily_report._EXCLUDED_IN_REPORT 同名单）：销户账户不进
        # 逐账户策略分析。月流水节不受影响（9月确有成交，历史留账）。
        _CLOSED = _load_closed_accounts()
        ids = [r["account_id"] for r in L.execute(
            "SELECT DISTINCT account_id FROM strategy_accounts "
            "WHERE date>=? AND date<=? ORDER BY account_id",
            (m_start_c, m_end_c))
            if r["account_id"] not in _CLOSED]
        problems = []
        for acc in ids:
            nav_rows = L.execute(
                "SELECT date,nav,cash,daily_ret,market_ret,n_pos FROM "
                "strategy_accounts WHERE account_id=? AND date>=? AND "
                "date<=? ORDER BY date",
                (acc, m_start_c, m_end_c)
            ).fetchall()
            if not nav_rows:
                continue
            mret = 1.0
            mkt = 1.0
            for r in nav_rows:
                if r["daily_ret"] is not None:
                    mret *= (1 + r["daily_ret"] / 100)
                if r["market_ret"] is not None:
                    mkt *= (1 + r["market_ret"] / 100)
            mret = (mret - 1) * 100
            mkt = (mkt - 1) * 100
            last = nav_rows[-1]
            # 月内最大回撤 + 区间（峰日→谷底日→修复日；只报深度不够，给区间才能归因事件）
            peak, peak_dt = 0.0, None
            mdd, mdd_peak, mdd_peak_dt, trough_dt = 0.0, 0.0, None, None
            rec_dt = None
            for r in nav_rows:
                if rec_dt is None and trough_dt is not None and r["nav"] >= mdd_peak:
                    rec_dt = r["date"]
                if peak > 0:
                    dd = r["nav"] / peak - 1
                    if dd < mdd:
                        # 创新低=新回撤段：修复日必须在该段低点之后重新找
                        # （10-02 v2 首跑修的 bug：段切换不重置 rec_dt 会留旧段日期，
                        #  报出"20260922→20260930（20260921修复）"这种修复早于谷底）
                        mdd, mdd_peak, mdd_peak_dt, trough_dt = dd, peak, peak_dt, r["date"]
                        rec_dt = None
                if r["nav"] > peak:
                    peak, peak_dt = r["nav"], r["date"]
            initial = meta[acc]["initial_capital"] if acc in meta else 1e6
            since = (last["nav"] / initial - 1) * 100
            a = agg.get(acc, {"bn": 0, "bs": 0, "sn": 0, "ss": 0})
            cash_pct = last["cash"] / last["nav"] * 100 if last["nav"] else 0
            name = meta[acc]["name"] if acc in meta else acc
            out.append(f"  ▶ {name}({acc}) {len(nav_rows)}个交易日")
            out.append(f"    月收益 {mret:+.2f}% vs 大盘 {mkt:+.2f}%"
                       f"（超额 {mret - mkt:+.2f}pp）｜成立以来 {since:+.2f}%"
                       f"｜月内最大回撤 {mdd * 100:.1f}%")
            out.append(f"    买{a['bn']}笔 {a['bs']:,.0f}／卖{a['sn']}笔"
                       f" {a['ss']:,.0f}｜现金占比 {cash_pct:.0f}%"
                       f"｜持仓 {last['n_pos']} 只")
            holds = L.execute(
                "SELECT name,shares,avg_cost FROM strategy_positions "
                "WHERE account_id=? AND shares>0 ORDER BY "
                "shares*avg_cost DESC LIMIT 3", (acc,)).fetchall()
            if holds:
                out.append("    重仓: " + "、".join(
                    f"{h['name']}" for h in holds))
            # —— v2 深度量化（确定性）——
            # ① 日均超额序列显著性（用户统计纪律：|t|<2 未达显著，样本不足禁下结论）
            excess = [(r["daily_ret"] - r["market_ret"]) for r in nav_rows
                      if r["daily_ret"] is not None and r["market_ret"] is not None]
            es = _tstat(excess)
            if es:
                emu, et, en, epos = es
                t_s = f"{et:+.2f}" if et is not None else "n/a"
                sig = "（未达显著）" if (et is not None and abs(et) < 2) else ""
                out.append(f"    日均超额 {emu:+.3f}%×{en}天 ｜ 超额为正 {epos}/{en} 天 ｜ "
                           f"超额t值 {t_s}{sig}")
            # ② 月换手 =（买额+卖额)/月内日均NAV —— 对照重评窗口判过度交易
            avg_nav = sum(r["nav"] for r in nav_rows) / len(nav_rows)
            turnover = (a["bs"] + a["ss"]) / avg_nav if avg_nav > 0 else 0
            # ③ 严格 FIFO（全历史建仓批次、只计月内平仓）：逐票已实现 + 平均持有天数
            q_lots = {}      # code -> [[剩余qty, 批次成本价, 建仓日], ...]（FIFO队列）
            per_code_real = {}  # code -> [name, 月内已实现]
            hold_days = []   # [(持有天数, 平仓qty)] 月内批次，数量加权
            close_n = 0
            for r in L.execute(
                    "SELECT code,name,direction,quantity,price,trade_date "
                    "FROM trade_log WHERE strategy=? AND trade_date<=? "
                    "ORDER BY trade_date, trade_time", (acc, m_end)):
                q, p = r["quantity"] or 0, r["price"] or 0.0
                td = str(r["trade_date"])[:10]
                if r["direction"] == "BUY":
                    q_lots.setdefault(r["code"], []).append([q, p, td])
                else:
                    queue = q_lots.get(r["code"], [])
                    need = q
                    while need > 0 and queue:
                        lot = queue[0]
                        take = min(need, lot[0])
                        if td >= m_start:
                            v = take * (p - lot[1])
                            pc = per_code_real.setdefault(r["code"], [r["name"], 0.0])
                            pc[1] += v
                            try:
                                hd = (date.fromisoformat(td) -
                                      date.fromisoformat(lot[2])).days
                                hold_days.append((hd, take))
                                close_n += 1
                            except ValueError:
                                pass
                        lot[0] -= take
                        need -= take
                        if lot[0] <= 0:
                            queue.pop(0)
            win_real = sum(v[1] for v in per_code_real.values())
            if hold_days:
                avg_hold = (sum(d * n for d, n in hold_days) /
                            sum(n for d, n in hold_days))
                hold_txt = f" ｜ 平仓笔平均持有 {avg_hold:.1f} 天(数量加权)"
            else:
                hold_txt = ""
            if trough_dt:
                rec_txt = (f"{mdd_peak_dt}→{trough_dt} {mdd*100:.1f}%"
                           f"（{rec_dt}修复）" if rec_dt else
                           f"{mdd_peak_dt}→{trough_dt} {mdd*100:.1f}%（月末未修复）")
            else:
                rec_txt = "月内未回撤"
            out.append(f"    月内已实现(严格FIFO) {win_real:+,.0f} ｜ 月内平仓 {close_n} 笔"
                       f"{hold_txt}")
            out.append(f"    月换手 {turnover:.1f}倍 ｜ 回撤区间 {rec_txt}")
            if per_code_real:
                srt = sorted(per_code_real.values(), key=lambda x: -x[1])
                best = "、".join(f"{v[0]}{v[1]:+,.0f}" for v in srt[:3] if v[1] > 0)
                worst = "、".join(f"{v[0]}{v[1]:+,.0f}" for v in reversed(srt[-3:]) if v[1] < 0)
                if best:
                    out.append(f"    贡献top: {best}")
                if worst:
                    out.append(f"    拖累top: {worst}")
            # 规则化问题判定
            flags = []
            if mret - mkt < -2:
                flags.append(f"跑输大盘{mkt - mret:.1f}pp")
            if since < -3:
                flags.append(f"成立以来亏{abs(since):.1f}%")
            if cash_pct > 50 and last["n_pos"] <= 5:
                flags.append(f"仓位仅{100 - cash_pct:.0f}%资金闲置")
            if abs(mdd) > 8:
                flags.append(f"月内回撤{mdd * 100:.1f}%超8%线")
            if len(nav_rows) < 10 and last["date"] < m_end_c[:8] + "20":
                flags.append(f"仅{len(nav_rows)}天数据(中途上线/停更)")
            # v2 过度交易哨兵（0829 策略哲学：反对过度交易。换手>2倍/月 且
            # 日均超额为负 = 白忙换手）
            if turnover > 2 and es and es[0] < 0:
                flags.append(f"高换手{turnover:.1f}倍/月且日均超额为负")
            if flags:
                problems.append((acc, name, flags))
        out.append("")
        out.append("【问题总结】")
        if problems:
            for acc, name, flags in problems:
                out.append(f"  ❌ {name}: " + "；".join(flags))
        else:
            out.append("  ✅ 无账户触发问题规则")
    except sqlite3.Error as e:
        out.append(f"  ⚠️ 逐账户分析段异常: {e}")

    # ── ③ 成交质量哨兵（月报是每日防线的月度复盘）──
    bad = L.execute(
        "SELECT COUNT(*) n FROM trade_log WHERE amount>0 AND price>0 AND "
        "ABS(quantity*price-amount) > 0.01*amount").fetchone()["n"]
    bad_m = L.execute(
        "SELECT COUNT(*) n FROM trade_log WHERE amount>0 AND price>0 AND trade_date>=? AND "
        "trade_date<=? AND ABS(quantity*price-amount) > 0.01*amount", (m_start, m_end)).fetchone()["n"]
    out.append("")
    out.append("【成交质量】")
    out.append(f"  全库量金不符(>1%): {bad} 笔 ／ 本月新增: {bad_m} 笔"
               + ("  ✅ 防线在线,增量断根" if bad_m == 0 else "  ❌ 查 exec_agent 截量回写"))

    # ── ⑦ 信号链月况（三表口径各异: ic_daily=signal_date+ic_final;
    # fusion/cmmr_ic_daily=date+ic 且日期混格式(裸码/ISO并存) → 一律 REPLACE 归一）
    # v2: 月均IC + IC>0天数 + t 显著性（用户统计纪律）──
    try:
        S = sqlite3.connect(f"file:{SIGNALS}?mode=ro", uri=True)
        S.row_factory = sqlite3.Row
        ics = []
        for tbl, dcol, ccol in [("ic_daily", "signal_date", "ic_final"),
                                 ("fusion_ic_daily", "date", "ic"),
                                 ("cmmr_ic_daily", "date", "ic")]:
            try:
                q = (f"SELECT {ccol} v FROM {tbl} "
                     f"WHERE REPLACE({dcol},'-','')>=? AND REPLACE({dcol},'-','')<=? "
                     f"AND {ccol} IS NOT NULL")
                vals = [r["v"] for r in S.execute(
                    q, (m_start_c, m_end_c)).fetchall()]
                res = _tstat(vals)
                if res:
                    mu, t, n, pos = res
                    t_s = f"{t:+.2f}" if t is not None else "n/a"
                    sig = "（未达显著）" if (t is not None and abs(t) < 2) else ""
                    ics.append(f"  {tbl:<18} 月均IC {mu:+.4f} (n={n}) ｜ "
                               f"IC>0 {pos}/{n} ｜ t {t_s}{sig}")
            except sqlite3.Error:
                pass
        if ics:
            out.append("")
            out.append(f"【信号链 {mon}】")
            out.extend(ics)
    except sqlite3.Error:
        pass

    out.append("")
    out.append(f"生成 {datetime.now():%F %H:%M} · MacBook 原生口径(ledger.db 只读)")
    report = "\n".join(out)

    if args.push:
        import subprocess
        # 与 daily_report.py QQ_TARGETS 同靶: 主 QQ(主人)
        p = subprocess.run(["hermes", "send", "-t",
                            "qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616"],
                           input=report.encode(), capture_output=True)
        if p.returncode != 0:
            print(f"🔴 [月报推送失败] {p.stderr.decode()[:200]}")
            sys.exit(1)
        print("已推送 qqbot")
    print(report)


if __name__ == "__main__":
    main()
