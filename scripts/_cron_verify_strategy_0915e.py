"""只读核查：cmmr_fusion 本轮 12 只"无实时价(停牌?)"是真停牌还是拉价失败。
1) 直连新浪 raw 抓取这 12 只 + 对照可交易票
2) fetch_prices_batch（脚本实际调用路径）
3) tushare.db 查它们最近交易日是否正常成交
"""
import os, sys, time, sqlite3

SD = os.path.expanduser("~/.hermes/stockdb")
sys.path.insert(0, SD)
os.chdir(SD)

CODES = ["001260", "003001", "300886", "301130", "600833", "603331",
         "603382", "603801", "605189", "688004", "688217", "688793"]
CTRL = ["603089", "605286"]  # 今日 09:35 实际成交的票（必然有价）

from core.prices import _fetch_sina, fetch_prices_batch  # noqa

t0 = time.time()
raw = _fetch_sina(CODES + CTRL)
print(f"[raw _fetch_sina] {len(raw)}/{len(CODES+CTRL)} in {time.time()-t0:.2f}s")
miss = [c for c in CODES if c not in raw]
print("  raw 缺价:", miss if miss else "无")
for c in CODES + CTRL:
    v = raw.get(c)
    print(f"   {c} {'OK ' + str(v.get('price')) if v else 'MISS'}")

t0 = time.time()
batch = fetch_prices_batch(CODES + CTRL)
print(f"[fetch_prices_batch] {len(batch)}/{len(CODES+CTRL)} in {time.time()-t0:.2f}s 缺:",
      [c for c in CODES if c not in batch])

import duckdb
con = duckdb.connect(os.path.join(SD, "tushare.db"), read_only=True)
q = "SELECT ts_code, MAX(trade_date) mx FROM daily WHERE ts_code IN (" + \
    ",".join("'%s.SZ'%c" % (c, '') for c in CODES) + " OR ts_code IN (" + \
    ",".join("'%s.SH'" % c for c in CODES) + ") GROUP BY 1 ORDER BY 1"
print("\n[tushare daily 最近交易日]")
mx = con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print("  daily 全表最大 trade_date =", mx)
for ts, m in con.execute(q).fetchall():
    print(f"   {ts} -> {m}")

c2 = sqlite3.connect(os.path.join(SD, "ledger.db"))
print("\n[trade_cooldown 命中?]")
for code in CODES:
    r = c2.execute("SELECT code,strategy,sell_date,status FROM trade_cooldown WHERE code=?", (code,)).fetchall()
    if r:
        print("  ", r)
