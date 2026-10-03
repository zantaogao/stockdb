"""stock_basic 名册周更（0927 审计建）——真·周更实现，单文件自包含。
背景：名册停更2个月，32只新上市股 LEFT JOIN 不上 → ST过滤 sb.name NOT LIKE 对 NULL 恒为假 → 融合信号被静默吞掉。
表: signals.db(SQLite) stock_basic(stock_code,name,industry,market,list_date)。
tushare stock_basic 接口无视 params.fields，恒返回10列固定顺序(ts_code,symbol,name,area,industry,cnspell,market,list_date,act_name,act_ent_type)，
本脚本按返回字段名动态定位对位，勿硬编码索引。"""
import os, sqlite3, json, urllib.request, sys

B = os.path.expanduser("~/.hermes/stockdb")
NEED = ["ts_code", "name", "industry", "market", "list_date"]

def refresh():
    tok = json.load(open(os.path.join(B, "config.json")))["tushare_token"]
    rows = []
    for st in ["L", "D", "P"]:
        payload = {"api_name": "stock_basic", "token": tok,
                   "params": {"exchange": "", "list_status": st,
                              "fields": "ts_code,name,industry,market,list_date"}}
        req = urllib.request.Request("http://api.tushare.pro", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
        if d.get("code") != 0:
            raise RuntimeError("tushare %s: %s" % (st, d.get("msg")))
        flds = d["data"]["fields"]
        ix = [flds.index(f) for f in NEED]  # 按字段名定位，接口加列/乱序都不怕
        rows.extend([[r[ix[0]].split(".")[0], r[ix[1]], r[ix[2]], r[ix[3]], r[ix[4]]]
                     for r in d["data"]["items"]])
    if len(rows) < 5000:
        raise RuntimeError("API只拉到%d行(<5000)，拒写" % len(rows))
    bad = [r for r in rows if not str(r[4] or "").isdigit()]
    S = sqlite3.connect(f"file:{B}/signals.db", timeout=120)
    S.execute("BEGIN")
    S.execute("DELETE FROM stock_basic")
    S.executemany("INSERT INTO stock_basic (stock_code,name,industry,market,list_date) VALUES (?,?,?,?,?)", rows)
    S.commit()
    return S, len(bad)

def verify(S, bad_n):
    n, d, mx = S.execute("SELECT COUNT(*), COUNT(DISTINCT stock_code), MAX(list_date) FROM stock_basic").fetchone()
    print(f"stock_basic: 行数={n} 唯一={d} 最晚上市={mx} list_date异常={bad_n}")
    if d != n:
        raise RuntimeError("名册有重复code")
    miss = S.execute("""SELECT COUNT(DISTINCT nf.stock_code) FROM new_factors nf
        WHERE nf.date=(SELECT MAX(date) FROM new_factors)
          AND nf.stock_code NOT IN (SELECT stock_code FROM fusion_3f_signals WHERE date=(SELECT MAX(date) FROM new_factors))
          AND nf.stock_code NOT IN (SELECT stock_code FROM stock_basic WHERE name LIKE '%ST%' OR name LIKE '%退%' OR market='北交所')""").fetchone()[0]
    # 残差应全为停牌退市整理期股（在册有行情但无信号属正常边界）
    print(f"核查: 最新日有因子无fusion、非ST非北交 = {miss}（残差应仅为停牌/退市整理股）")
    S.close()

if __name__ == "__main__":
    S, bad_n = refresh()
    verify(S, bad_n)
