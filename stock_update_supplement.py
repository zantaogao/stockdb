#!/usr/bin/env python3
"""
A股补充数据每日更新：板块、资金流向、ETF、基金排名、基金规模
由 daily_update.py 在股票/基金净值更新后调用
"""
import os, sys, time, duckdb, pandas as pd
from core.db import TUSHARE_DB_PATH, get_tushare_db

BASE = Path.home() / '.hermes' / 'stockdb'
# STOCK_DB 已废弃，现在统一用 TUSHARE_DB_PATH
FUND_DB = os.path.join(BASE, "fund.db")
LOG = os.path.join(BASE, "logs", "supplement_update.log")

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


def update_money_flow():
    """更新资金流向（今日全市场）"""
    import akshare as ak
    log("📊 更新资金流向...")
    db = duckdb.connect(str(TUSHARE_DB_PATH))
    # 先checkpoint确保之前写入落盘，避免并发冲突
    try:
        db.execute("CALL checkpoint()")
    except Exception:
        pass
    today = date.today()

    try:
        df = ak.stock_individual_fund_flow_rank(indicator='今日')
        if df.empty:
            log("  ⚠️ 资金流向数据为空")
            return False

        inserted = 0
        for _, r in df.iterrows():
            code = str(r['代码']).strip().zfill(6)

            def safe_float(val):
                if pd.isna(val) or str(val).strip() in ('-', '', '--'):
                    return 0.0
                try:
                    return float(val)
                except:
                    return 0.0

            main_net = safe_float(r.get('今日主力净流入-净额'))
            main_pct = safe_float(r.get('今日主力净流入-净占比'))
            retail_net = safe_float(r.get('今日小单净流入-净额'))

            db.execute(
                "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?,?,?,?,?)",
                [code, today, main_net, retail_net, main_pct]
            )
            inserted += 1

        db.commit()
        log(f"  ✅ 资金流向更新: {inserted}只股票")
        return True
    except Exception as e:
        log(f"  ❌ 资金流向更新失败: {e}")
        return False
    finally:
        db.close()


def update_board_daily():
    """更新板块日线"""
    import akshare as ak
    log("📊 更新板块日线...")
    db = duckdb.connect(str(TUSHARE_DB_PATH))
    # 先checkpoint确保之前写入落盘，避免并发冲突
    try:
        db.execute("CALL checkpoint()")
    except Exception:
        pass
    today = date.today()

    try:
        df = ak.stock_board_industry_name_em()
        if df.empty:
            log("  ⚠️ 板块数据为空")
            return False

        inserted = 0
        for _, r in df.iterrows():
            name = r['板块名称']
            close = float(r['最新价'])
            change_pct = float(r['涨跌幅'])
            volume = int(float(r.get('换手率', 0)) * 1e4)  # 换手率间接估算成交量
            amount = 0  # 没有成交额数据

            db.execute(
                "INSERT OR REPLACE INTO board_daily (board_code, date, open, close, high, low, volume, amount, change_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                [name, today, close, close, close, close, volume, amount, change_pct]
            )
            inserted += 1

        db.commit()
        log(f"  ✅ 板块日线更新: {inserted}个板块")
        return True
    except Exception as e:
        log(f"  ❌ 板块日线更新失败: {e}")
        return False
    finally:
        db.close()


def update_etf_daily():
    """更新ETF日线（用AKShare批量接口）"""
    import akshare as ak
    log("📊 更新ETF日线...")
    db = duckdb.connect(FUND_DB)
    today = date.today()

    try:
        df = ak.fund_etf_spot_em()
        if df.empty:
            log("  ⚠️ ETF实时数据为空")
            return False

        inserted = 0
        for _, r in df.iterrows():
            code = str(r['代码']).strip()
            price = float(r['最新价']) if pd.notna(r.get('最新价')) else None
            premium = float(r['基金折价率']) if pd.notna(r.get('基金折价率')) else None
            volume = int(float(r['成交量'])) if pd.notna(r.get('成交量')) else 0
            amount = float(r['成交额']) if pd.notna(r.get('成交额')) else 0

            # 检查是否已有今日数据
            last = db.execute("SELECT MAX(date) FROM etf_daily WHERE fund_code=?", [code]).fetchone()[0]
            if last and last >= today:
                continue

            db.execute(
                "INSERT OR REPLACE INTO etf_daily (fund_code, date, nav, price, premium_pct, volume, amount) VALUES (?,?,?,?,?,?,?)",
                [code, today, None, price, premium, volume, amount]
            )
            inserted += 1

        db.commit()
        log(f"  ✅ ETF日线更新: {inserted}只新增, 共{len(df)}只")
        return True
    except Exception as e:
        log(f"  ❌ ETF日线更新失败: {e}")
        return False
    finally:
        db.close()


def update_fund_rank():
    """从基金净值计算阶段收益排名（1w/1m/3m/6m/1y）"""
    log("📊 计算基金阶段收益排名...")
    db = duckdb.connect(FUND_DB)
    today = date.today()

    periods = {
        '1w': 7, '1m': 30, '3m': 90, '6m': 180, '1y': 365,
    }

    total_inserted = 0
    for period_name, delta_days in periods.items():
        start_date = today - timedelta(days=delta_days)
        # 用SQL批量计算：每只基金取周期首尾净值
        sql = f"""
        WITH ranked AS (
            SELECT fund_code, unit_nav, date,
                   ROW_NUMBER() OVER (PARTITION BY fund_code ORDER BY date) as rn_first,
                   ROW_NUMBER() OVER (PARTITION BY fund_code ORDER BY date DESC) as rn_last
            FROM fund_nav_daily 
            WHERE date >= '{start_date}' AND date <= '{today}'
            AND unit_nav IS NOT NULL AND unit_nav > 0
        )
        SELECT r1.fund_code, 
               ROUND((r2.unit_nav - r1.unit_nav) / r1.unit_nav * 100, 2) as return_rate
        FROM ranked r1
        JOIN ranked r2 ON r1.fund_code = r2.fund_code
        WHERE r1.rn_first = 1 AND r2.rn_last = 1
        ORDER BY return_rate DESC
        """
        rows = db.execute(sql).fetchall()
        total = len(rows)

        # 批量写入排名
        inserted = 0
        batch = []
        for rank, (code, ret) in enumerate(rows, 1):
            batch.append((code, today, period_name, ret, rank, total))
            inserted += 1

        if batch:
            db.executemany(
                "INSERT OR REPLACE INTO fund_rank (fund_code, report_date, period, return_rate, rank, total_count) VALUES (?,?,?,?,?,?)",
                batch
            )
            db.commit()

        total_inserted += inserted
        log(f"  {period_name}: {inserted}只基金已排名")

    log(f"  ✅ 基金排名更新完成: 共{total_inserted}条")
    db.close()
    return True


def update_fund_size():
    """更新基金规模（用AKShare实时接口）"""
    import akshare as ak
    log("📊 更新基金规模...")
    db = duckdb.connect(FUND_DB)
    today = date.today()

    try:
        df = ak.fund_scale_open_sina()
        if df.empty:
            log("  ⚠️ 基金规模接口返回空")
            return False

        inserted = 0
        for idx in df.index:
            code = str(df.at[idx, '基金代码']).strip()
            shares = float(df.at[idx, '最近总份额']) if pd.notna(df.at[idx, '最近总份额']) else 0
            nav = float(df.at[idx, '单位净值']) if pd.notna(df.at[idx, '单位净值']) else 0
            size = shares * nav if shares > 0 and nav > 0 else 0

            if size > 0:
                db.execute(
                    "INSERT OR REPLACE INTO fund_size (fund_code, report_date, size) VALUES (?,?,?)",
                    [code, today, size]
                )
                inserted += 1

        db.commit()
        log(f"  ✅ 基金规模更新: {inserted}/{len(df)}只")
        return True
    except Exception as e:
        log(f"  ❌ 基金规模更新失败: {e}")
        return False
    finally:
        db.close()


def main():
    log("=" * 60)
    log("📊 A股补充数据每日更新")
    log(f"日期: {date.today()}")
    log("=" * 60)

    results = {}

    log("\n--- 第1步: 资金流向更新 ---")
    results['money_flow'] = "✅" if update_money_flow() else "❌"

    log("\n--- 第2步: 板块日线更新 ---")
    results['board_daily'] = "✅" if update_board_daily() else "❌"

    log("\n--- 第3步: ETF日线更新 ---")
    results['etf_daily'] = "✅" if update_etf_daily() else "❌"

    log("\n--- 第4步: 基金排名更新 ---")
    results['fund_rank'] = "✅" if update_fund_rank() else "❌"

    log("\n--- 第5步: 基金规模更新 ---")
    results['fund_size'] = "✅" if update_fund_size() else "❌"

    log("\n" + "=" * 60)
    log("📋 补充更新汇总")
    for k, v in results.items():
        log(f"  {v} {k}")
    log("=" * 60)

    failures = [k for k, v in results.items() if v == "❌"]
    if failures:
        print(f"\n⚠️ 以下更新失败: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("\n✅ 全部更新完成")
        sys.exit(0)


if __name__ == '__main__':
    main()
