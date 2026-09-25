import sqlite3, duckdb
codes = ['301082','300305','301137','301395','605179','002861','300001','300316','600160','600777']
cands = []
for c in codes:
    for suf in ('.SZ', '.SH', '.BJ'):
        cands.append(c + suf)
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ph = ",".join(["?"] * len(cands))
rows = d.execute(f"SELECT ts_code, name FROM stock_basic WHERE ts_code IN ({ph})", cands).fetchall()
d.close()
name_map = {r[0][:6]: r[1] for r in rows}
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
data = c.execute("""
    SELECT stock_code, fusion_3f_score, flow_alpha, reg10
    FROM fusion_3f_signals
    WHERE REPLACE(date,'-','')='20260803' AND signal='强买'
    ORDER BY fusion_3f_score DESC, flow_alpha DESC LIMIT 10
""").fetchall()
c.close()
for code, score, flow, reg10 in data:
    print(f"  {code} {name_map.get(code,'?'):8s} score={score} flow={flow:.4f} reg10={reg10:.4f}")
