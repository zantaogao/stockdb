import sqlite3, datetime
today = datetime.date.today().strftime('%Y%m%d')
BASE = '/Users/zantao/.hermes/stockdb'

# 1. signal_history 重复检查
c = sqlite3.connect(BASE + '/signals.db', timeout=10)
total = c.execute("SELECT COUNT(*) FROM signal_history").fetchone()[0]
dups = c.execute("""SELECT COUNT(*) FROM (SELECT REPLACE(date,'-','') d, stock_code, COUNT(*) n
  FROM signal_history GROUP BY 1,2 HAVING n>1)""").fetchone()[0]
today_rows = c.execute("SELECT COUNT(*) FROM signal_history WHERE REPLACE(date,'-','')=?", (today,)).fetchone()[0]
print("signal_history 总行数:", total, "| 重复组(date+code+type计>1):", dups, "| 今日行数:", today_rows)
# 重复集中在哪些日期
try:
    top = c.execute("""SELECT d, COUNT(*) FROM (SELECT REPLACE(date,'-','') d, stock_code, COUNT(*) n
      FROM signal_history GROUP BY 1,2 HAVING n>1) GROUP BY d ORDER BY COUNT(*) DESC LIMIT 8""").fetchall()
    print("重复最多的日期TOP8:", top)
except Exception as e:
    print("top dup 查询失败:", e)
c.close()

# 2. ca_run_log
c = sqlite3.connect(BASE + '/ledger.db', timeout=10)
try:
    r = c.execute("SELECT run_date,status,n_ex,n_hit FROM ca_run_log ORDER BY run_date DESC LIMIT 5").fetchall()
    print("ca_run_log 最近5次:", r)
    today_rec = c.execute("SELECT status,n_ex,n_hit,detail FROM ca_run_log WHERE REPLACE(run_date,'-','')=?", (today,)).fetchone()
    print("今日 ca_run_log:", today_rec)
except Exception as e:
    print("ca_run_log 查询失败:", e)
hold = [x[0] for x in c.execute("SELECT DISTINCT stock_code FROM holdings").fetchall()]
print("持仓数:", len(hold))
c.close()

# 3. 持仓股今日除权（tushare.daily 里看今日是否有除权除息——用 dividend/stk_limit 太绕，直接查今日 ex_date）
try:
    import duckdb
    d = duckdb.connect(BASE + '/tushare.db', read_only=True)
    ex = d.execute(f"SELECT ts_code, ex_date FROM dividend WHERE ex_date IN ('{today}','{today[:4]}-{today[4:6]}-{today[6:]}')").fetchall()
    holdset = set(hold)
    hit = [x for x in ex if x[0].split('.')[0] in holdset]
    print("全市场今日除权只数:", len(ex), "| 命中持仓:", hit)
    d.close()
except Exception as e:
    print("dividend 查询失败:", e)
