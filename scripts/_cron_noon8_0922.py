import sqlite3, os, urllib.request, json
os.chdir('/Users/zantao/.hermes/stockdb')
c = sqlite3.connect('ledger.db')
holds = c.execute("SELECT code,name,avg_cost,shares,target_price,stop_loss,buy_date FROM holdings WHERE status='hold'").fetchall()
def sina_code(code):
    return ('sh' if code.startswith(('6','9')) else 'sz') + code
lst = ",".join(sina_code(h[0]) for h in holds)
url = "https://hq.sinajs.cn/list=" + lst
req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://finance.sina.com.cn"})
d = urllib.request.urlopen(req, timeout=10).read().decode("gbk","ignore")
q = {}
for line in d.strip().split("\n"):
    if '="' not in line: continue
    key = line.split("=")[0].split("_")[-1]
    f = line.split('"')[1].split(",")
    q[key] = {"name": f[0], "prev": float(f[2]), "now": float(f[3]), "high": float(f[4]), "low": float(f[5])}
tot_today = 0.0; tot_val = 0.0
print(f"{'代码':8}{'名称':8}{'成本':>8}{'现价':>8}{'昨收':>8}{'今日%':>7}{'累计%':>7}{'距止盈%':>8}{'距止损%':>8}  今日盈亏元")
for code,name,cost,sh,tp,sl,bd in holds:
    k = sina_code(code)
    if k not in q: print(code, "no quote"); continue
    now = q[k]["now"]; prev = q[k]["prev"]
    daypct = (now/prev-1)*100; cum = (now/cost-1)*100
    dtp = (tp/now-1)*100; dsl = (sl/now-1)*100
    pnl = (now-prev)*sh
    tot_today += pnl; tot_val += now*sh
    flag = " 🎯止盈" if now>=tp else (" 🛑止损" if now<=sl else "")
    print(f"{code:8}{name:8}{cost:>8.2f}{now:>8.2f}{prev:>8.2f}{daypct:>+7.2f}{cum:>+7.1f}{dtp:>+8.1f}{dsl:>+8.1f}  {pnl:>+10.0f}{flag}")
print("持仓市值(实时) %.0f  今日盘口盈亏 %.0f 现金 759 总资产约 %.0f" % (tot_val, tot_today, tot_val+759))
