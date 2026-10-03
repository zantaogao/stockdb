import os, sqlite3, json, urllib.request
B = os.path.expanduser("~/.hermes/stockdb")
tok = json.load(open(os.path.expanduser("~/.hermes/stockdb/config.json")))["tushare_token"]
rows_all = []
for st in ["L", "D", "P"]:
    payload = {"api_name": "stock_basic", "token": tok, "params": {"exchange": "", "list_status": st, "fields": "ts_code,symbol,name,area,industry,market,list_date"}}
    req = urllib.request.Request("http://api.tushare.pro", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())
    if d.get("code") != 0:
        print("API失败", st, d.get("msg")); raise SystemExit(1)
    rows_all.extend(d["data"]["items"])
print("API拉到:", len(rows_all))
S = sqlite3.connect(f"file:{B}/signals.db", timeout=120)
cols = [c[1] for c in S.execute("PRAGMA table_info(stock_basic)")]
print("表列:", cols)
idx = {"ts_code": 0, "symbol": 1, "name": 2, "area": 3, "industry": 4, "market": 5, "list_date": 6}
S.execute("BEGIN")
S.execute("DELETE FROM stock_basic")
sql = "INSERT INTO stock_basic (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols)))
ins = []
for r in rows_all:
    ins.append([r[idx[c]] if c in idx else None for c in cols])
S.executemany(sql, ins)
S.commit()
n = S.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
mx = S.execute("SELECT MAX(list_date) FROM stock_basic").fetchone()[0]
st = S.execute("SELECT COUNT(*) FROM stock_basic WHERE name LIKE '%ST%' OR name LIKE '%退%'").fetchone()[0]
print("刷新后 rows:", n, "最晚上市:", mx, "ST/退:", st)
miss = S.execute("SELECT COUNT(DISTINCT nf.stock_code) FROM new_factors nf WHERE nf.date='2026-09-24' AND nf.stock_code NOT IN (SELECT stock_code FROM fusion_3f_signals WHERE date='2026-09-24') AND nf.stock_code NOT IN (SELECT stock_code FROM stock_basic WHERE name LIKE '%ST%' OR name LIKE '%退%' OR market='北交所')").fetchone()[0]
print("复核: 0924有因子但无fusion信号、非ST非北交(应0):", miss)
S.close()
