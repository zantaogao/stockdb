"""
批量补 10 只候选股的钱流数据（2025-12 至 2026-05）
"""
import requests
import duckdb
import time

BASE = "/Users/zantao/.hermes/stockdb"
DB = f"{BASE}/stock.db"

connection = db.get_tushare_db()

def fetch_money_flow(code, start_date, end_date):
    """
    获取某只股票某段时间内的钱流数据
    push2delay 接口返回格式：https://push2delay.eastmoney.com/quote/getFilterStockFundData
    """
    params = {
        "filter": f"{code}",
        "end": end_date,
        "start": start_date,
        "pag": "1",
        "pageIndex": "1",
        "pageSize": "200",
        "fields": "fund1,fund2",
        "ut": "fa5fd1ce4c7aeb364ba6409908c8be09",
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://quote.eastmoney.com/",
    }
    
    url = f"https://push2delay.eastmoney.com/quote/getFilterStockFundData?{params["filter"]}={params["end"]}&{params["start"]}&{params["end"]}&{params["pag"]}&{params["pageIndex"]}&{params["pageSize"]}&{params["fields"]}&{params["ut"]}&{params["ut"]}".replace("&", "&")
    
    r = requests.get(url, headers=headers, timeout=30)
    
    # 解析 JSON 数据
    if r.text.startswith("{"):
        import json
        d = json.loads(r.text)
        data = d.get("data", {}).get("diff")
        return data
    
    return None

def save_to_db(code, data):
    """保存到 money_flow 表"""
    try:
        # 插入到数据库
        insert_sql = """
        INSERT INTO money_flow (stock_code, date, in_flow, net_inflow, flow, percent)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(stock_code, date) DO UPDATE SET
            in_flow = EXCLUDED.in_flow,
            net_inflow = EXCLUDED.net_inflow,
            flow = EXCLUDED.flow,
            percent = EXCLUDED.percent
        """
        
        # 处理数据
        for item in data:
            # 字段：fund1: 主力净流入 (亿), fund2: 超大单净流入 (亿)
            # 需要映射：in_flow, net_inflow, flow, percent
            
            in_flow = item.get("fund1", "")
            net_inflow = item.get("fund2", "")
            flow = item.get("flow", "")
            percent = item.get("percent", "")
            date = item.get("date", "")
            
            # 插入
            connection.execute(insert_sql, [code, date, in_flow, net_inflow, flow, percent])
            
        return True
    except Exception as e:
        print(f"\n代码{code} 插入失败：{e}")
        return False

# 10 只候选股
codes = [
    ("688552", "航天南湖"),
    ("300395", "菲利华"),
    ("301219", "腾远钴业"),
    ("002805", "丰元股份"),
    ("301150", "中一科技"),
    ("688101", "三达膜"),
    ("301035", "润丰股份"),
    ("002170", "芭田股份"),
    ("600724", "宁波富达"),
    ("688013", "天臣医疗"),
]

# 分批补数据（2025-12 至 2026-05，约 5 个月）
print("=" * 60)
print("补钱流数据（2025-12 至 2026-05）")
print("=" * 60)

started_at = time.time()

for idx, (code, name) in enumerate(codes, 1):
    print(f"\n[{idx}/{len(codes)}] 补{code} {name}")
    
    # 补 12 个月数据（2025-06 至 2026-05）
    for month in range(6, 13):
        start_date = f"2025-{month+1:02d}-01"
        end_date = f"2026-{month+1:02d}-01"
        
        result = fetch_money_flow(code, start_date, end_date)
        if result:
            inserted = save_to_db(code, result)
            if inserted:
                month_cnt = len(result)
                print(f"  ✓ {month}/2025 月补了{month_cnt}天")
        else:
            print(f"  ✗ {month}/2025 月数据为空")
        
        time.sleep(0.3)  # 速率控制

print(f"\n总计耗时：{time.time()-started_at:.0f}秒")
print("\n更新完成，请重新运行 scoring.py 或复盘.py")

connection.close()
