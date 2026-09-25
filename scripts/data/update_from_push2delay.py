#!/usr/bin/env python3
"""
push2delay 数据源补充更新脚本
用于盘后更新 money_flow、ETF 等补充表，修复换手率
使用 push2delay.eastmoney.com (push2 的替代域名，延迟15分钟但稳定可用)
"""
import os, sys, json, re, time, duckdb, requests, urllib.request
from datetime import date, datetime
from urllib.parse import urlencode

BASE = os.path.expanduser("~/.hermes/stockdb")
STOCK_DB = os.path.join(BASE, "stock.db")
FUND_DB = os.path.join(BASE, "fund.db")
LOG = os.path.join(BASE, "logs", "push2delay_update.log")

PUSH2DELAY = "https://push2delay.eastmoney.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

DRY_RUN = "--dry-run" in sys.argv

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {'[DRY] ' if DRY_RUN else ''}{msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def fetch_clist(params, page_all=False):
    """调 push2delay clist 接口，返回 diff 列表
    page_all=True 时自动翻页获取全部数据"""
    items = []
    page = 1
    while True:
        p = dict(params, pn=page)
        url = f"{PUSH2DELAY}/api/qt/clist/get?" + urlencode(p)
        r = requests.get(url, headers=HEADERS, timeout=20)
        m = re.search(r"\{.*\}", r.text)
        if not m:
            log(f"  ⚠️ push2delay 返回格式异常: {r.text[:100]}")
            break
        d = json.loads(m.group())
        if d.get("rc") != 0:
            if page == 1:
                log(f"  ⚠️ push2delay rc={d.get('rc')}: 数据不可用")
            break
        batch = d.get("data", {}).get("diff", [])
        items.extend(batch)
        if not page_all or not batch:
            break
        total = d.get("data", {}).get("total", 0)
        if len(items) >= total:
            break
        page += 1
        time.sleep(0.3)  # 不要太快
    return items

# ============ 1. 资金流向更新 ============

def get_latest_trade_date():
    db = duckdb.connect(STOCK_DB)
    try:
        r = db.execute('SELECT MAX(date) FROM stock_daily').fetchone()
        return r[0] if r[0] else date.today()
    finally:
        db.close()

def update_money_flow():
    """从 push2delay 获取全市场资金流向"""
    log("📊 更新资金流向...")
    today = get_latest_trade_date()
    
    params = {
        "pn": 1, "pz": 100, "po": 1, "np": 1,
        "fields": "f12,f14,f62,f84,f184",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2+f:!2",
    }
    items = fetch_clist(params, page_all=True)
    if not items:
        log("  ⚠️ 资金流向数据为空")
        return False
    
    log(f"  获取 {len(items)} 只股票的资金流向数据")
    
    if DRY_RUN:
        item = items[0]
        log(f"  示例: {item.get('f14')} main_net={item.get('f62')} retail_net={item.get('f84')} main_pct={item.get('f184')}")
        # 验证单位
        main_net = item.get("f62", 0) or 0
        main_pct_raw = item.get("f184", 0) or 0
        main_pct = main_pct_raw / 100.0
        log(f"  单位验证: main_net={main_net}(元), main_pct={main_pct_raw}/100={main_pct}%")
        return True
    
    db = duckdb.connect(STOCK_DB)
    inserted = 0
    try:
        db.execute("BEGIN TRANSACTION")
        # 先删今日旧数据
        db.execute(f"DELETE FROM money_flow WHERE date = '{today}'")
        
        for item in items:
            code = str(item.get("f12", "")).strip().zfill(6)
            if not code or len(code) != 6:
                continue
            main_net = float(item.get("f62", 0) or 0)
            retail_net = float(item.get("f84", 0) or 0)
            main_pct_raw = float(item.get("f184", 0) or 0)
            main_pct = round(main_pct_raw / 100.0, 2)
            
            db.execute(
                "INSERT OR REPLACE INTO money_flow (stock_code, date, main_net, retail_net, main_pct) VALUES (?, ?, ?, ?, ?)",
                [code, today, main_net, retail_net, main_pct],
            )
            inserted += 1
        
        db.execute("COMMIT")
        log(f"  ✅ 资金流向: 写入 {inserted} 条")
    except Exception as e:
        db.execute("ROLLBACK")
        log(f"  ❌ 资金流向写入失败: {e}")
        return False
    finally:
        db.close()
    return True

# ============ 2. ETF 日线更新 ============

def update_etf_daily():
    """从 push2delay 获取 ETF 实时数据"""
    log("📊 更新 ETF 日线...")
    today = get_latest_trade_date()
    
    params = {
        "pn": 1, "pz": 2000, "po": 1, "np": 1,
        "fields": "f12,f14,f2,f3,f4,f62,f184,f8,f20",
        "fs": "m:0+t:3+f:!2",
    }
    items = fetch_clist(params)
    if not items:
        log("  ⚠️ ETF 数据为空")
        return False
    
    log(f"  获取 {len(items)} 只 ETF 数据")
    
    if DRY_RUN:
        for item in items[:3]:
            log(f"  ETF示例: {item.get('f14')} price={item.get('f2')} chg={item.get('f3')}")
        return True
    
    db = duckdb.connect(FUND_DB)
    inserted = 0
    try:
        # 检查 etf_daily 表是否存在
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='etf_daily'").fetchall()
        if not tables:
            log("  ⏭ etf_daily 表不存在，跳过")
            db.close()
            return False
        
        db.execute("BEGIN TRANSACTION")
        for item in items:
            code = str(item.get("f12", "")).strip()
            if not code:
                continue
            price = float(item.get("f2", 0) or 0)
            chg = (item.get("f3", 0) or 0) / 100.0
            volume = int(item.get("f20", 0) or 0)
            amount = float(item.get("f62", 0) or 0)  # ETF 的 f62 可能是成交额
            
            db.execute(
                "INSERT OR REPLACE INTO etf_daily (fund_code, date, price, premium_pct, volume, amount) VALUES (?, ?, ?, ?, ?, ?)",
                [code, today, price, chg, volume, amount],
            )
            inserted += 1
        
        db.execute("COMMIT")
        log(f"  ✅ ETF日线: 写入 {inserted} 只")
    except Exception as e:
        db.execute("ROLLBACK")
        log(f"  ❌ ETF日线写入失败: {e}")
        return False
    finally:
        db.close()
    return True

# ============ 3. 换手率修复 ============

def fix_turnover_rate():
    """从 push2delay 获取换手率补填 stock_daily 数据"""
    log("📊 补填换手率...")
    today = get_latest_trade_date()
    
    params = {
        "pn": 1, "pz": 100, "po": 1, "np": 1,
        "fields": "f12,f14,f8",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2+f:!2",
    }
    items = fetch_clist(params, page_all=True)
    if not items:
        log("  ⚠️ 换手率数据为空")
        return False
    
    log(f"  获取 {len(items)} 只股票的换手率")
    
    if DRY_RUN:
        for item in items[:3]:
            tr_raw = item.get("f8", 0) or 0
            tr = tr_raw / 100.0  # 万分比转百分比
            log(f"  {item.get('f14')}: f8={tr_raw} → turn_rate={tr}%")
        return True
    
    db = duckdb.connect(STOCK_DB)
    updated = 0
    try:
        db.execute("BEGIN TRANSACTION")
        for item in items:
            code = str(item.get("f12", "")).strip().zfill(6)
            tr_raw = float(item.get("f8", 0) or 0)
            tr = round(tr_raw / 100.0, 2)
            if tr == 0:
                continue
            db.execute(
                "UPDATE stock_daily SET turn_rate = ? WHERE stock_code = ? AND date = ?",
                [tr, code, today],
            )
            updated += 1
        db.execute("COMMIT")
        log(f"  ✅ 换手率补填: 更新 {updated} 只")
    except Exception as e:
        db.execute("ROLLBACK")
        log(f"  ❌ 换手率更新失败: {e}")
        return False
    finally:
        db.close()
    return True

# ============ 4. 指数日线更新（新浪API） ============

SINA_INDEXES = {
    "sh000001": "000001",
    "sz399001": "399001",
    "sz399006": "399006",
    "sh000688": "000688",
    "sh000300": "000300",
    "sh000016": "000016",
    "sh000905": "000905",
    "sz399852": "399852",
}

def update_index_daily():
    """从新浪获取指数行情，增量更新 index_daily"""
    log("📊 更新指数日线...")
    today = date.today()
    symbols = ",".join(SINA_INDEXES.keys())
    url = f"https://hq.sinajs.cn/list={symbols}"
    
    try:
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=15).read()
        text = raw.decode("gbk")
    except Exception as e:
        log(f"  ❌ 新浪指数接口失败: {e}")
        return False
    
    db = duckdb.connect(STOCK_DB)
    updated = 0
    try:
        db.execute("BEGIN TRANSACTION")
        for line in text.strip().split("\n"):
            if "hq_str_" not in line:
                continue
            try:
                data = line.split('"')[1].split(",")
                sina_code = line.split("hq_str_")[1].split("=")[0]
                code = SINA_INDEXES.get(sina_code)
                if not code or len(data) < 33:
                    continue
                open_p = float(data[1])
                prev_close = float(data[2])
                close_p = float(data[3])
                high_p = float(data[4])
                low_p = float(data[5])
                volume = int(float(data[8]))  # 股
                amount = float(data[9])       # 元
                change_pct = round((close_p - prev_close) / prev_close * 100, 2)
                
                # 检查是否已有今日数据
                last = db.execute("SELECT MAX(date) FROM index_daily WHERE index_code=?", [code]).fetchone()[0]
                if last and last >= today:
                    continue
                
                db.execute(
                    "INSERT INTO index_daily (index_code, date, open, close, high, low, volume, amount, change_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [code, today, open_p, close_p, high_p, low_p, volume, amount, change_pct],
                )
                updated += 1
            except:
                pass
        db.execute("COMMIT")
        log(f"  ✅ 指数日线: 更新 {updated} 个指数")
    except Exception as e:
        db.execute("ROLLBACK")
        log(f"  ❌ 指数写入失败: {e}")
        return False
    finally:
        db.close()
    return True


# ============ 5. 板块日线更新（push2delay + 前日收盘推算） ============

def update_board_daily():
    """从 push2delay 获取板块涨跌幅，结合前日收盘价推算今日数据"""
    log("📊 更新板块日线...")
    today = date.today()
    
    params = {
        "pn": 1, "pz": 100, "po": 1, "np": 1,
        "fields": "f12,f14,f3,f4,f20",
        "fs": "m:90+t:2+f:!2",
    }
    items = fetch_clist(params, page_all=True)
    if not items:
        log("  ⚠️ 板块数据为空")
        return False
    
    log(f"  获取 {len(items)} 个板块")
    
    if DRY_RUN:
        for item in items[:3]:
            chg = (item.get("f3", 0) or 0) / 100.0
            log(f"  {item.get('f14')}: change={chg}%")
        return True
    
    db = duckdb.connect(STOCK_DB)
    updated = 0
    try:
        # 预加载每个板块前一日收盘价
        prev_closes = {}
        rows = db.execute(
            "SELECT board_code, close FROM (SELECT board_code, close, ROW_NUMBER() OVER (PARTITION BY board_code ORDER BY date DESC) rn FROM board_daily) WHERE rn=1"
        ).fetchall()
        for r in rows:
            prev_closes[r[0]] = r[1]
        
        db.execute("BEGIN TRANSACTION")
        # 删今日旧数据
        db.execute(f"DELETE FROM board_daily WHERE date = '{today}'")
        
        for item in items:
            code = str(item.get("f12", "")).strip()
            name = str(item.get("f14", "")).strip()
            chg_raw = float(item.get("f3", 0) or 0)
            chg = round(chg_raw / 100.0, 2)  # 万分比转百分比
            
            # 用前日收盘 + 涨跌幅算今日收盘
            prev_close = prev_closes.get(code)
            if prev_close and prev_close > 0:
                close_p = round(prev_close * (1 + chg / 100), 2)
            else:
                close_p = 0.0
            
            db.execute(
                "INSERT OR REPLACE INTO board_daily (board_code, date, open, close, high, low, volume, amount, change_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [code, today, close_p, close_p, close_p, close_p, 0, 0, chg],
            )
            updated += 1
        
        db.execute("COMMIT")
        log(f"  ✅ 板块日线: 更新 {updated} 个板块")
    except Exception as e:
        db.execute("ROLLBACK")
        log(f"  ❌ 板块写入失败: {e}")
        return False
    finally:
        db.close()
    return True


# ============ main ============

def main():
    log("=" * 60)
    log(f"📊 push2delay 补充数据更新")
    log(f"日期: {date.today()}")
    log("=" * 60)
    
    results = {}

    log("\n--- 第1步: 资金流向更新 ---")
    mf_ok = update_money_flow()
    results["money_flow"] = "✅" if mf_ok else "❌"

    # 统计沪市+科创板缺少资金流的数量
    sh_missing = 0
    sh_missing_codes = []
    if mf_ok:
        try:
            db = duckdb.connect(STOCK_DB)
            today_str = str(get_latest_trade_date())
            rows = db.execute("""
                SELECT stock_code FROM money_flow
                WHERE date = ?
            """, [today_str]).fetchall()
            updated_codes = set(r[0] for r in rows)

            all_stocks = db.execute("""
                SELECT DISTINCT stock_code FROM stock_daily
                WHERE date = ?
            """, [today_str]).fetchall()
            all_codes = set(r[0] for r in all_stocks)

            missing = all_codes - updated_codes
            sh_missing = len(missing)
            sh_missing_codes = sorted(list(missing))[:10]
            db.close()
        except:
            pass

    log("\n--- 第2步: ETF日线更新 ---")
    try:
        results["etf_daily"] = "✅" if update_etf_daily() else "⏭"
    except Exception as e:
        log(f"  ⚠️ ETF 跳过: {e}")
        results["etf_daily"] = "⏭"

    log("\n--- 第3步: 换手率补填 ---")
    results["turn_rate"] = "✅" if fix_turnover_rate() else "❌"

    log("\n--- 第4步: 指数日线更新 ---")
    results["index_daily"] = "✅" if update_index_daily() else "❌"

    log("\n--- 第5步: 板块日线更新 ---")
    results["board_daily"] = "✅" if update_board_daily() else "❌"

    log("\n" + "=" * 60)
    log("📋 补充更新汇总")
    for k, v in results.items():
        log(f"  {v} {k}")
    log("=" * 60)

    if sh_missing > 0:
        log(f"\n⚠️ 注意: 有 {sh_missing} 只股票无资金流数据（沪市+科创板）")
        log("   科创板688xx东财clist接口暂不支持")
        log(f"   样例: {', '.join(sh_missing_codes[:5])}...")
        log("   scoring.py的维度跳过机制会忽略缺失的资金面维度")

    failures = [k for k, v in results.items() if v == "❌"]
    if failures:
        log(f"⚠️ 以下更新失败: {', '.join(failures)}")
        return 1
    log("✅ 全部完成")
    return 0

if __name__ == "__main__":
    sys.exit(main())
