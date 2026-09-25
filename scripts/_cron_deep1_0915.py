# -*- coding: utf-8 -*-
"""盘后深复盘取数（2026-09-15，只读）。
输出：A 板块矩阵 / B 指数 / C 账户与仓位距离 / D IC 序列 / E 个股形态诊断
"""
import duckdb, sqlite3, os, json
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TS = os.path.join(BASE, 'tushare.db')
con = duckdb.connect(TS, read_only=True)
lc = sqlite3.connect(os.path.join(BASE, 'ledger.db'))
lc.row_factory = sqlite3.Row
sc = sqlite3.connect(os.path.join(BASE, 'signals.db'))

TODAY = '20260915'


def suffix(c):
    c = str(c)
    if '.' in c:
        return c
    return c + ('.SH' if c.startswith(('6', '68', '9')) else '.SZ')


def bare(ts_code):
    return str(ts_code).split('.')[0]


# ---------- 交易日 ----------
days = [r[0] for r in con.execute(
    "SELECT DISTINCT trade_date FROM daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 40", (TODAY,)).fetchall()]
last6 = list(reversed(days[:6]))
print("=" * 90)
print("A. 行业板块（stock_basic.industry × daily 均值，最近6个交易日）")
print("交易日:", last6)

ind_map = {}
for code, ind in con.execute("SELECT ts_code, industry FROM stock_basic WHERE industry IS NOT NULL AND industry != ''").fetchall():
    ind_map[bare(code)] = ind

# 每日行业均值
q = ','.join('?' * len(last6))
rows = con.execute(f"""
    SELECT trade_date, ts_code, pct_chg FROM daily
    WHERE trade_date IN ({q}) AND pct_chg IS NOT NULL
""", last6).fetchall()
byday = defaultdict(list)
codeset = set()
for d, code, p in rows:
    b = bare(code)
    ind = ind_map.get(b)
    if ind:
        byday[(str(d), ind)].append(float(p))
        codeset.add(b)

# 近5日累计（成员个股5日收益均值）
d5 = list(reversed(days[:6]))
cum = defaultdict(list)
rows5 = con.execute(f"""
    SELECT trade_date, ts_code, close FROM daily
    WHERE trade_date IN ({','.join('?' * len(d5))})
""", d5).fetchall()
prices = defaultdict(dict)
for d, code, c in rows5:
    prices[bare(code)][str(d)] = float(c)
first_d, last_d = d5[0], d5[-1]
for b, ser in prices.items():
    if first_d in ser and last_d in ser and ser[first_d] > 0:
        ind = ind_map.get(b)
        if ind:
            cum[ind].append(ser[last_d] / ser[first_d] - 1)

indstats = {}
for ind in set(list(cum.keys())):
    daily = [sum(byday.get((d, ind), [])) / len(byday[(d, ind)]) if byday.get((d, ind)) else None for d in last6]
    c5 = sum(cum[ind]) / len(cum[ind]) * 100 if cum[ind] else None
    if daily[-1] is None:
        continue
    # 连续强势天数：从最后一天往前，日均涨幅>0 的连续天数
    streak = 0
    for x in reversed(daily):
        if x is not None and x > 0:
            streak += 1
        else:
            break
    # 相对全市场当日均值的超额（最近一天）
    indstats[ind] = {
        'daily': daily, 'cum5': c5, 'n': len(cum[ind]), 'streak': streak,
        'today_dev': None,
    }

mkt_daily = []
for i, d in enumerate(last6):
    vals = []
    for (dd, ind), lst in byday.items():
        if dd == d:
            vals += lst
    mkt_daily.append(sum(vals) / len(vals) if vals else 0)
print("  全市场日均涨幅序列:", " ".join(f"{d[4:]}:{v:+.2f}%" for d, v in zip(last6, mkt_daily)))

rank = sorted(indstats.items(), key=lambda kv: (kv[1]['daily'][-1] if kv[1]['daily'][-1] is not None else -99), reverse=True)
print(f"  共 {len(rank)} 个行业（按今日均值涨幅排序，列顺序 {last6} 即 0908→0915，n>=3）")
print("  行业             " + "  ".join(d[4:] for d in last6) + "    5日累计 连强  n")
for ind, st in rank[:12] + rank[-8:]:
    if st['n'] < 3:
        continue
    ds = "  ".join(f"{x:+.2f}" if x is not None else "  -- " for x in st['daily'])
    print(f"  {ind:<16} {ds}   {st['cum5']:+6.2f}%  {st['streak']:>2}  {st['n']}")

print("\n  5日累计排名前12:")
for ind, st in sorted(indstats.items(), key=lambda kv: kv[1]['cum5'] if kv[1]['cum5'] is not None else -99, reverse=True)[:12]:
    if st['n'] < 3:
        continue
    print(f"  {ind:<16} 5日 {st['cum5']:+6.2f}%  今日 {st['daily'][-1]:+.2f}%  连强{st['streak']}  n={st['n']}")

print("\n  5日累计排名后8:")
for ind, st in sorted(indstats.items(), key=lambda kv: kv[1]['cum5'] if kv[1]['cum5'] is not None else -99)[:8]:
    if st['n'] < 3:
        continue
    print(f"  {ind:<16} 5日 {st['cum5']:+6.2f}%  今日 {st['daily'][-1]:+.2f}%  连强{st['streak']}  n={st['n']}")

# ---------- B. 指数 ----------
print("\n" + "=" * 90)
print("B. 指数近12日（上证/中证1000/上证50/创业板/沪深300）")
for code, nm in [('000001.SH', '上证'), ('000852.SH', '中证1000'), ('000016.SH', '上证50'), ('399006.SZ', '创业板'), ('000300.SH', '沪深300')]:
    rr = con.execute("SELECT trade_date, close, pct_chg FROM index_daily_raw WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 12", (code, TODAY)).fetchall()
    rr = list(reversed(rr))
    closes = [float(x[1]) for x in rr]
    ma10 = sum(closes[-10:]) / 10
    print(f"  {nm}({code}): 今 {closes[-1]:.2f}")
    print("     " + "  ".join(f"{str(x[0])[4:]}:{float(x[2]):+.2f}" for x in rr))
    print(f"     MA10={ma10:.2f} 今收距MA10 {(closes[-1]/ma10-1)*100:+.2f}%  近12日高 {max(closes):.2f} 低 {min(closes):.2f}")

# ---------- C. 账户与仓位距离 ----------
print("\n" + "=" * 90)
print("\nC. 主账户持仓（ledger.holdings）风控距离")
for r in lc.execute("SELECT * FROM holdings WHERE status='hold'").fetchall():
    code, name = r['code'], (r['name'] or '')
    px = float(r['latest_price'] or 0)
    tp = float(r['target_price'] or 0)
    sl = float(r['stop_loss'] or 0)
    cost = float(r['avg_cost'] or 0)
    pnlp = r['pnl_pct']
    d_tp = (tp / px - 1) * 100 if tp and px else None
    d_sl = (px / sl - 1) * 100 if sl and px else None
    val = px * float(r['shares'] or 0)
    pnls = f"{float(pnlp):>+6.2f}%" if pnlp is not None else "     -"
    dtps = f"{d_tp:>+6.1f}%" if d_tp is not None else "     -"
    dsls = f"{d_sl:>+6.1f}%" if d_sl is not None else "     -"
    print(f"  {code} {name:<8} 股数{int(r['shares'] or 0):>6} 成本{cost:>7.2f} 现价{px:>7.2f} 盈亏{pnls} "
          f"市值{val:>9.0f} 目标{tp:>7.2f}(距{dtps}) 止损{sl:>7.2f}(距{dsls}) 买{r['buy_date']}")

print("\n  position_peaks:")
for r in lc.execute("SELECT * FROM position_peaks").fetchall():
    print("   ", tuple(r))

print("\n  watchlist(最新扫描日 >= 20260911):")
for r in lc.execute("""SELECT ts_code, score, scan_date, status, entry_low, entry_high, target_price, stop_loss, source
                       FROM watchlist WHERE scan_date >= '20260911' ORDER BY scan_date DESC, score DESC LIMIT 40""").fetchall():
    print("   ", tuple(r))

print("\n  strategy_accounts_meta:")
for r in lc.execute("SELECT account_id,name,initial_capital,cash,config_json FROM strategy_accounts_meta").fetchall():
    print(f"   {r[0]:<14} {r[1]:<16} init={r[2]} cash={r[3]} cfg={r[4]}")

print("\n  策略持仓（按账户）:")
for r in lc.execute("""SELECT account_id, code, name, shares, avg_cost, buy_date, peak_price, stop_loss, target
                       FROM strategy_positions ORDER BY account_id, code""").fetchall():
    print("   ", tuple(r))

print("\n  trade_log 近2日:")
for r in lc.execute("SELECT * FROM trade_log WHERE date(COALESCE(created_at,''))>=date('2026-09-14') ORDER BY id DESC LIMIT 30").fetchall():
    print("   ", dict(r))

print("\n  account_balance:")
for r in lc.execute("SELECT * FROM account_balance").fetchall():
    print("   ", tuple(r))

# ---------- D. IC 序列 ----------
print("\n" + "=" * 90)
print("D. IC 序列")
print("  ic_daily 近12行 (signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion, ic_final, top_ret, bottom_ret):")
for r in sc.execute("SELECT signal_date, sample_size, ic_reg10, ic_reg20, ic_reg40, ic_fusion, ic_final, top_ret, bottom_ret FROM ic_daily ORDER BY REPLACE(signal_date,'-','') DESC LIMIT 12").fetchall():
    print("   ", tuple(r))
print("  fusion_ic_daily 近12行:")
for r in sc.execute("SELECT * FROM fusion_ic_daily ORDER BY REPLACE(date,'-','') DESC LIMIT 12").fetchall():
    print("   ", tuple(r))
print("  center_dual_ic_daily 近12行:")
for r in sc.execute("SELECT * FROM center_dual_ic_daily ORDER BY REPLACE(date,'-','') DESC LIMIT 12").fetchall():
    print("   ", tuple(r))
print("  ic_window 近10行:")
cols = [c[1] for c in sc.execute("PRAGMA table_info(ic_window)").fetchall()]
for r in sc.execute("SELECT * FROM ic_window ORDER BY REPLACE(signal_date,'-','') DESC LIMIT 10").fetchall():
    print("   " + " ".join(f"{c}={v}" for c, v in zip(cols, r)))

con.close()
lc.close()
sc.close()
