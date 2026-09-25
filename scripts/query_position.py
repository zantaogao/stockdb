#!/usr/bin/env python3
"""查持仓/流水：主账号 + 全策略账号，一次查全。
用法: query_position.py <股票名或代码> [--trades N]
口径(09-03实查): ledger.db holdings(主账号) / strategy_positions(策略) / trade_log(流水,strategy列区分账号)
"""
import sqlite3, sys, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ledger.db')

def resolve(cur, q):
    """先按代码精确查，再按名称模糊查（stock_basic 在 signals.db）"""
    if q.isdigit():
        return q
    s = sqlite3.connect(os.path.join(os.path.dirname(DB), 'signals.db'))
    rows = s.execute("select stock_code,name from stock_basic where name like ?", (f'%{q}%',)).fetchall()
    s.close()
    if not rows:
        # 兜底：从持仓/流水里找
        rows = cur.execute("select distinct code,name from trade_log where name like ?", (f'%{q}%',)).fetchall()
    if not rows:
        return None
    for c, n in rows:
        if n == q:
            return c
    return rows[0][0]

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__); sys.exit(1)
    q = args[0]
    ntr = 20
    if '--trades' in sys.argv:
        ntr = int(sys.argv[sys.argv.index('--trades') + 1])
    c = sqlite3.connect(DB)
    code = resolve(c.cursor(), q)
    if not code:
        # 空结果=红灯：已查 stock_basic + trade_log 两路径均无 → 报"查无此票"
        print(f"查无此票: {q}（已查 signals.db.stock_basic + ledger.db.trade_log 两路径）"); sys.exit(2)
    print(f"股票: {code}")

    print("\n[主账号持仓] 来源 ledger.db.holdings")
    rows = c.execute("select name,status,buy_date,avg_cost,shares,pnl_pct from holdings where code=?", (code,)).fetchall()
    print("\n".join(f"  {r}" for r in rows) or "  无")

    print("\n[策略账号持仓] 来源 ledger.db.strategy_positions")
    rows = c.execute("select account_id,name,shares,avg_cost,buy_date from strategy_positions where code=?", (code,)).fetchall()
    print("\n".join(f"  {r}" for r in rows) or "  无")

    print(f"\n[最近{ntr}笔流水] 来源 ledger.db.trade_log")
    rows = c.execute("select strategy,trade_date,direction,price,quantity from trade_log where code=? order by trade_date desc limit ?", (code, ntr)).fetchall()
    print("\n".join(f"  {r}" for r in rows) or "  无")

    print("\n[观察池] 来源 ledger.db.watchlist")
    rows = c.execute("select status,scan_date,score,source from watchlist where ts_code=?", (code,)).fetchall()
    print("\n".join(f"  {r}" for r in rows) or "  无")
    c.close()

if __name__ == '__main__':
    main()