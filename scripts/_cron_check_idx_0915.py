#!/usr/bin/env python3
import duckdb, urllib.request
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print("=== index_daily 中证1000 最近6日 ===")
for r in con.execute("SELECT date, index_code, close, change_pct FROM index_daily WHERE index_code LIKE '000852%' ORDER BY date DESC LIMIT 6").fetchall():
    print("  ", r)
print("=== 000852 全部index_code取值 ===")
print(con.execute("SELECT DISTINCT index_code FROM index_daily WHERE index_code LIKE '%852%'").fetchall())
try:
    req = urllib.request.Request("https://hq.sinajs.cn/list=sh000852", headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
    parts = raw.split('"')[1].split(',')
    print("=== 新浪实时 sh000852 ===")
    print("  名称:", parts[0], "今开:", parts[1], "昨收:", parts[2], "现价:", parts[3], "涨跌:", round(float(parts[3]) - float(parts[2]), 2), f"({(float(parts[3])/float(parts[2])-1)*100:+.2f}%)", "时间:", parts[30] if len(parts) > 30 else "?")
except Exception as e:
    print("  实时获取失败:", e)
