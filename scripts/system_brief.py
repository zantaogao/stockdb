#!/usr/bin/env python3
"""system_brief.py — 交易系统当前状态简报生成器。

会话开始/需要时运行，输出当前系统状态摘要（持仓/最新信号/数据新鲜度/cron健康），
注入上下文让模型开窗即知系统状态，无需全系统查找。

用法:
    python3 -B scripts/system_brief.py          # 完整简报
    python3 -B scripts/system_brief.py --short  # 精简版（关键数字）
"""
import sys
import os
import json
import sqlite3
import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_STOCKDB = os.path.dirname(_SCRIPT_DIR)
if _STOCKDB not in sys.path:
    sys.path.insert(0, _STOCKDB)

import duckdb

SHORT = "--short" in sys.argv


def q(sql, conn=None):
    """统一查询入口，适配 date 双格式。"""
    pass


def brief():
    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"# 交易系统状态简报 ({now})")

    # 1. 数据新鲜度 (tushare.db)
    try:
        td = duckdb.connect(os.path.join(_STOCKDB, "tushare.db"), read_only=True)
        last_date = td.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
        n = td.execute(f"SELECT COUNT(*) FROM daily WHERE trade_date='{last_date}'").fetchone()[0]
        # 判断是否最新交易日（跳过周末）
        today = datetime.date.today()
        lines.append(f"\n## 数据新鲜度")
        lines.append(f"daily 最新交易日: {last_date} ({n} 只)")
        if SHORT:
            lines = lines[:1] + lines[2:]
            td.close()
            return "\n".join(lines)
        lines.append(f"今天是 {today}（周{'一二三四五六日'[today.weekday()]}）")
        # stk_factor 最新
        try:
            sf = td.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]
            lines.append(f"stk_factor 最新: {sf}")
        except Exception:
            pass
        # ETF
        try:
            etf = td.execute("SELECT MAX(trade_date) FROM fund_daily").fetchone()[0]
            lines.append(f"fund_daily(ETF) 最新: {etf}")
        except Exception:
            pass
        td.close()
    except Exception as e:
        lines.append(f"\n## 数据新鲜度\n❌ tushare.db 读取失败: {e}")

    # 2. 持仓 + 账户 (ledger.db v2热层)
    try:
        st = sqlite3.connect(os.path.join(_STOCKDB, "ledger.db"))  # v2热层
        lines.append(f"\n## 持仓 ({now[:10]})")
        try:
            pos = st.execute("SELECT * FROM holdings").fetchall()
            cols = [d[0] for d in st.execute("SELECT * FROM holdings LIMIT 0").description]
            if pos:
                lines.append(f"共 {len(pos)} 只持仓")
                for row in pos:
                    d = dict(zip(cols, row))
                    code = d.get("stock_code") or d.get("code") or "?"
                    shares = d.get("shares") or d.get("quantity") or 0
                    cost = d.get("avg_cost") or d.get("cost_price") or 0
                    price = d.get("latest_price") or 0
                    lines.append(f"  {code}: {shares}股 @成本{cost} 现价{price}")
            else:
                lines.append("（空仓）")
        except Exception as e:
            lines.append(f"holdings 读取失败: {e}")
        try:
            bal = st.execute("SELECT * FROM account_balance ORDER BY rowid DESC LIMIT 1").fetchone()
            if bal:
                cols = [d[0] for d in st.execute("SELECT * FROM account_balance LIMIT 0").description]
                d = dict(zip(cols, bal))
                cash = d.get("cash_balance") or d.get("cash") or "?"
                lines.append(f"可用现金: {cash}")
        except Exception as e:
            lines.append(f"account_balance 读取失败: {e}")
        st.close()
    except Exception as e:
        lines.append(f"\n## 持仓\n❌ ledger.db 读取失败: {e}")

    # 3. 最新信号
    try:
        st = sqlite3.connect(os.path.join(_STOCKDB, "signals.db"))  # v2温层
        lines.append(f"\n## 最新信号")
        try:
            latest = st.execute(
                "SELECT MAX(REPLACE(date,'-','')) FROM signal_history"
            ).fetchone()[0]
            if latest:
                lines.append(f"signal_history 最新日: {latest}")
                # 当日信号分布
                dist = st.execute(
                    f"SELECT industry, COUNT(*) FROM signal_history "
                    f"WHERE REPLACE(date,'-','')='{latest}' GROUP BY industry ORDER BY 2 DESC LIMIT 3"
                ).fetchall()
                for ind, cnt in dist:
                    lines.append(f"  {ind}: {cnt} 条")
        except Exception as e:
            lines.append(f"signal_history: {e}")
        try:
            fl = st.execute(
                "SELECT MAX(REPLACE(date,'-','')) FROM fusion_3f_signals"
            ).fetchone()[0]
            if fl:
                lines.append(f"fusion_3f 最新日: {fl}")
                sb = st.execute(
                    f"SELECT COUNT(*) FROM fusion_3f_signals WHERE REPLACE(date,'-','')='{fl}' AND signal='强买'"
                ).fetchone()[0]
                ss = st.execute(
                    f"SELECT COUNT(*) FROM fusion_3f_signals WHERE REPLACE(date,'-','')='{fl}' AND signal='强卖'"
                ).fetchone()[0]
                lines.append(f"  强买: {sb} 强卖: {ss}")
        except Exception as e:
            lines.append(f"fusion_3f: {e}")
        # IC 最新
        try:
            ic = st.execute("SELECT MAX(REPLACE(CAST(signal_date AS TEXT),'-','')) FROM ic_daily").fetchone()[0]
            if ic:
                lines.append(f"ic_daily 最新: {ic}")
        except Exception:
            pass
        st.close()
    except Exception as e:
        lines.append(f"\n## 最新信号\n❌ {e}")

    # 4. Cron 健康
    try:
        cron_path = os.path.expanduser("~/.hermes/cron/jobs.json")
        with open(cron_path) as f:
            jobs = json.load(f).get("jobs", [])
        lines.append(f"\n## Cron ({len(jobs)} 任务)")
        bad = [j for j in jobs if j.get("last_status") and j["last_status"] != "ok"]
        if bad:
            lines.append(f"⚠️ {len(bad)} 个任务上次未成功:")
            for j in bad[:5]:
                lines.append(f"  {j.get('name','?')}: {j.get('last_status')}")
        else:
            lines.append("全部正常（上次运行 ok）")
    except Exception as e:
        lines.append(f"\n## Cron\n❌ {e}")

    # 5. 面板健康
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8081/", timeout=3)
        lines.append(f"\n## 面板: ✅ 8081 运行中")
    except Exception:
        lines.append(f"\n## 面板: ❌ 8081 未响应")

    return "\n".join(lines)


if __name__ == "__main__":
    print(brief())
