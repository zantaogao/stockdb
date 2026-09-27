import duckdb, json
conn = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
for t in ['stock_daily','stock_valuation']:
    cols = [c[0] for c in conn.execute(f"describe {t}").fetchall()]
    n = conn.execute(f"select count(*), min(date), max(date) from {t}").fetchone() if 'date' in cols else conn.execute(f"select count(*) from {t}").fetchone()
    print(t, 'cols:', cols)
    print('  count/range:', n)
    r = conn.execute(f"select * from {t} limit 2").fetchall()
    print('  sample:', r)
# 9/7 旧样本构建脚本是谁？
import subprocess
out = subprocess.run(['grep','-rln','samples_v4.parquet','scripts/'], capture_output=True, text=True, cwd='/Users/zantao/.hermes/stockdb').stdout
print('引用 samples_v4 的脚本:', out)
# 旧 stats 检查 f17-22 的 mean/std（若=占位常数则 std≈0）
s = json.load(open('/Users/zantao/.hermes/stockdb/models/v10_v3_stats.json'))
for j in range(15,23):
    k = f'feat_{j}'
    if k in s: print('v3_stats', k, {kk: round(vv,4) for kk,vv in s[k].items()})
