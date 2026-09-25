import sqlite3

# Exact date formats for 2026-09-01 (today) in each signals table
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
nf = sig.execute("SELECT COUNT(*) FROM new_factors WHERE REPLACE(date,'-','')='20260901'").fetchone()[0]
print('new_factors 0901:', nf)
f3 = sig.execute("SELECT COUNT(*) FROM fusion_3f_signals WHERE REPLACE(signal_date,'-','')='20260901'").fetchone()[0]
print('fusion_3f 0901:', f3)
fc = sig.execute("SELECT COUNT(*) FROM fusion_center_signals WHERE REPLACE(trade_date,'-','')='20260901'").fetchone()[0]
print('fusion_center 0901:', fc)
# latest for each
print('nf latest:', sig.execute("SELECT date FROM new_factors ORDER BY date DESC LIMIT 1").fetchone())
print('f3 latest:', sig.execute("SELECT signal_date FROM fusion_3f_signals ORDER BY signal_date DESC LIMIT 1").fetchone())
print('fc latest:', sig.execute("SELECT trade_date FROM fusion_center_signals ORDER BY trade_date DESC LIMIT 1").fetchone())