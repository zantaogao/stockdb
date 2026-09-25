#!/usr/bin/env python3
# 异常归因：哨兵IC连负 vs 市场环境 + ETF IC + 真窗口IC
import sqlite3, duckdb, json

st = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/signals.db?mode=ro', uri=True)
st.row_factory = sqlite3.Row

print('=== ic_daily 近12条（哨兵IC，T+1验证）===')
for r in st.execute("SELECT signal_date,ic_fusion,ic_reg10,ic_reg20,ic_reg40,top_ret,bottom_ret FROM ic_daily ORDER BY signal_date DESC LIMIT 12"):
    print(f"{r['signal_date']}: fus={r['ic_fusion']:+.3f} 10d={r['ic_reg10']:+.3f} 20d={r['ic_reg20']:+.3f} 40d={r['ic_reg40']:+.3f} top10%={r['top_ret']} bot10%={r['bottom_ret']}")

print()
print('=== etf_ic 近10条 ===')
for r in st.execute("SELECT signal_date,ic_etf,ic_spearman,top_ret,bottom_ret,sample_size FROM etf_ic ORDER BY signal_date DESC LIMIT 10"):
    print(f"{r['signal_date']}: pear={r['ic_etf']:+.3f} spear={r['ic_spearman']:+.3f} top={r['top_ret']} bot={r['bottom_ret']} n={r['sample_size']}")

print()
print('=== factor_ic_roll 关键行 ===')
for r in st.execute("SELECT factor_name,mean_ic,win_rate,n_days FROM factor_ic_roll ORDER BY factor_name"):
    print(f"{r['factor_name']}: mean_ic={r['mean_ic']} win={r['win_rate']} n_days={r['n_days']}")

print()
print('=== 市场环境（daily 全市场宽度）===')
ts = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
rows = ts.execute("""
    SELECT trade_date,
           AVG(pct_chg) avg_ret,
           SUM(CASE WHEN pct_chg>0 THEN 1 ELSE 0 END)*1.0/COUNT(*) up_ratio,
           COUNT(*) n
    FROM daily
    WHERE trade_date >= '20260901'
    GROUP BY trade_date ORDER BY trade_date
""").fetchall()
for d,a,u,n in rows:
    print(f"{d}: 均涨={a:+.2f}% 涨占比={u*100:.0f}% n={n}")

print()
print('=== ic_window 近6条（真窗口）===')
for r in st.execute("SELECT signal_date,ic_fusion_w10,ic_reg10_w10,ic_3f_w10,ic_cmmrf_w10,ic_dual_w10,fwd10_top FROM ic_window ORDER BY signal_date DESC LIMIT 6"):
    print(dict(r))
