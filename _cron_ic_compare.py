"""cron IC 监控对比分析 - 读取 state.db 历史 IC 数据"""
import sqlite3

conn = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 70)
print("1. ic_daily 最近 15 个信号日 (模型IC)")
print("=" * 70)
rows = cur.execute("""
    SELECT signal_date, ic_fusion, ic_reg10, ic_reg20, ic_reg40,
           sample_size, top_ret, bottom_ret, ic_diff
    FROM ic_daily
    ORDER BY signal_date DESC LIMIT 15
""").fetchall()
for r in rows:
    print(f"{r['signal_date']} | fusion={r['ic_fusion']:+.4f} 10d={r['ic_reg10']:+.4f} "
          f"20d={r['ic_reg20']:+.4f} 40d={r['ic_reg40']:+.4f} | n={r['sample_size']} "
          f"top={r['top_ret']:+.2f}% bot={r['bottom_ret']:+.2f}% diff={r['ic_diff']:.2f}%")

print()
print("=" * 70)
print("2. factor_ic_roll 最近记录 (20日滚动IC)")
print("=" * 70)
rows = cur.execute("""
    SELECT as_of_date, factor_name, mean_ic, n_days, win_rate, window
    FROM factor_ic_roll
    ORDER BY as_of_date DESC, factor_name
    LIMIT 50
""").fetchall()
for r in rows:
    print(f"{r['as_of_date']} | {r['factor_name']:<18} mean_ic={r['mean_ic']:+.4f} "
          f"n_days={r['n_days']} win={r['win_rate']:.3f} win={r['window']}")

print()
print("=" * 70)
print("3. factor_group_ic_daily 最近 4 个 calc_date (特征分组日IC)")
print("=" * 70)
rows = cur.execute("""
    SELECT calc_date, factor_name, ic, sample_size
    FROM factor_group_ic_daily
    ORDER BY calc_date DESC, factor_name
    LIMIT 55
""").fetchall()
for r in rows:
    print(f"{r['calc_date']} | {r['factor_name']:<18} ic={r['ic']:+.4f} n={r['sample_size']}")

conn.close()
