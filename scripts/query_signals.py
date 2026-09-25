#!/usr/bin/env python3
"""查三链信号 + 近N日top10出现记录。
用法: query_signals.py <股票名或代码> [--days 12]
口径(09-03实查, 三链日期格式不同勿混):
  signal_history        日期YYYYMMDD, top10=按 final_score 降序前10名
  fusion_3f_signals     日期YYYY-MM-DD, 按 fusion_3f_score 降序; 100分并列极多(09-03实测),
                        "top10"无区分度, 此链只报逐日分数不算名次
  fusion_center_signals 日期YYYYMMDD, rank_pct越大越看多, top10=按 rank_pct 降序前10名
top10名次定义(与23:55报告/面板一致): row_number 按当日全市场排, 并列时按扫描顺序定先后。
"""
import sqlite3, sys, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'signals.db')

def resolve(c, q):
    if q.isdigit():
        return q
    rows = c.execute("select stock_code,name from stock_basic where name like ?", (f'%{q}%',)).fetchall()
    if not rows:
        return None
    for cd, n in rows:
        if n == q:
            return cd
    return rows[0][0]

def daily(c, table, date_col, code_col, sel, code, days, dstyle):
    """逐日信号。dstyle: 'compact'=YYYYMMDD, 'dash'=YYYY-MM-DD"""
    fmt, mod = ('%Y%m%d', 1) if dstyle == 'compact' else ('%Y-%m-%d', 0)
    from datetime import date, timedelta
    mx = c.execute(f"select max({date_col}) from {table}").fetchone()[0]
    if not mx:
        return []
    s = mx if not mod else f"{mx[:4]}-{mx[4:6]}-{mx[6:8]}"
    d0 = (date(int(s[:4]), int(s[5:7]), int(s[8:10])) - timedelta(days=days)).strftime(fmt)
    return c.execute(f"select {sel} from {table} where {code_col}=? and {date_col}>=? order by {date_col}", (code, d0)).fetchall()

def top_rank(c, table, date_col, code_col, order_col, asc, code, d0, dstyle):
    """逐日算该票名次(仅对top10出现检测; order_asc=False 表示值大者靠前)"""
    out = []
    dir_ = 'asc' if asc else 'desc'
    for (d,) in c.execute(f"select distinct {date_col} from {table} where {date_col}>=?", (d0,)):
        rk = c.execute(f"select r from (select {code_col}, row_number() over (order by {order_col} {dir_}) r from {table} where {date_col}=?) where {code_col}=?", (d, code)).fetchone()
        if rk and rk[0] <= 10:
            out.append((d, rk[0]))
    return out

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__); sys.exit(1)
    days = 12
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    code = resolve(c, args[0])
    if not code:
        print(f"查无此票: {args[0]}（已查 signals.db.stock_basic）"); sys.exit(2)
    print(f"股票: {code}  窗口: 近{days}自然日")

    print("\n[三模型 signal_history] signals.db.signal_history.final_score")
    rows = daily(c, 'signal_history', 'date', 'stock_code', 'date,final_score', code, days, 'compact')
    print("\n".join(f"  {d} {s}" for d, s in rows) or "  窗口内无记录")

    print("\n[fusion_3f] signals.db.fusion_3f_signals (100分并列多,不排名)")
    rows = daily(c, 'fusion_3f_signals', 'date', 'stock_code', 'date,fusion_3f_score,signal', code, days, 'dash')
    print("\n".join(f"  {d} {s} {sig}" for d, s, sig in rows) or "  窗口内无记录")

    print("\n[fusion_center] signals.db.fusion_center_signals")
    rows = daily(c, 'fusion_center_signals', 'date', 'stock_code', 'date,score,rank_pct,signal', code, days, 'compact')
    print("\n".join(f"  {d} score={s} rank_pct={p} {sig}" for d, s, p, sig in rows) or "  窗口内无记录")

    print(f"\n[top10出现记录 近{days}日]")
    from datetime import date as D, timedelta
    mx = c.execute("select max(date) from signal_history").fetchone()[0]
    d0_sh = (D(int(mx[:4]),int(mx[4:6]),int(mx[6:8])) - timedelta(days=days)).strftime('%Y%m%d')
    mx2 = c.execute("select max(date) from fusion_center_signals").fetchone()[0]
    d0_fc = (D(int(mx2[:4]),int(mx2[4:6]),int(mx2[6:8])) - timedelta(days=days)).strftime('%Y%m%d')
    h1 = top_rank(c, 'signal_history', 'date', 'stock_code', 'final_score', False, code, d0_sh, 'compact')
    h2 = top_rank(c, 'fusion_center_signals', 'date', 'stock_code', 'rank_pct', False, code, d0_fc, 'compact')
    hits = [f"signal_history({d} 第{r}名)" for d, r in h1] + [f"fusion_center({d} 第{r}名)" for d, r in h2]
    print("\n".join(f"  {x}" for x in hits) or "  近窗口未进过 signal_history/fusion_center top10")
    c.close()

if __name__ == '__main__':
    main()