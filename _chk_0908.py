import sqlite3, duckdb, json, urllib.request

# 候选非持仓票：查昨收与现价（tushare.db daily 最新两天）
cands = ['600137','300100','688638','001256','603079','688175','300539','301131','301632','688360']
db = duckdb.connect('tushare.db', read_only=True)
dts = [r[0] for r in db.execute("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 3").fetchall()]
print('recent trade dates:', dts)
prev = dts[0] if dts[0] != '20260908' else dts[1]
# 今日盘中价：tushare daily 可能还没今日数据，用新浪实时
inlist = ",".join("'%s.SZ' if False else x" for x in [])
ph = ",".join("?" for _ in cands)
rows = db.execute(f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [prev]+[c+('.SS' if c.startswith(('6','9')) else '.SZ') for c in cands]).fetchall()
prev_close = {r[0]: r[1] for r in rows}
print('prev_close', prev_close)

def sina(code):
    pre = 'sh' if code.startswith(('6','9')) else 'sz'
    url = f'http://hq.sinajs.cn/list={pre}{code}'
    req = urllib.request.Request(url, headers={'Referer':'http://finance.sina.com.cn'})
    txt = urllib.request.urlopen(req, timeout=8).read().decode('gbk')
    parts = txt.split('"')[1].split(',')
    return float(parts[3]), float(parts[2])  # now, prevclose

for code in cands:
    try:
        now, pc = sina(code)
        # 涨停价判断
        limit = pc*1.1 if not code.startswith(('68','30')) else pc*1.2
        print(code, 'now=%.2f prev=%.2f chg%%=%.2f nearLimit=%s' % (now, pc, (now/pc-1)*100, now >= limit*0.985))
    except Exception as e:
        print(code, 'ERR', e)