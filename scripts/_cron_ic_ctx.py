import sqlite3, os, statistics, math
db = os.path.expanduser('~/.hermes/stockdb/signals.db')
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
print('--- monthly means ---')
for r in c.execute("""SELECT substr(signal_date,1,7) ym, COUNT(*),
    ROUND(AVG(ic_reg10),4), ROUND(AVG(ic_reg20),4), ROUND(AVG(ic_reg40),4), ROUND(AVG(ic_fusion),4)
    FROM ic_daily GROUP BY ym ORDER BY ym DESC LIMIT 5"""):
    print(r)
print('--- last 10 sessions ---')
rows = c.execute("""SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion
    FROM ic_daily ORDER BY signal_date DESC LIMIT 10""").fetchall()[::-1]
for r in rows: print(r[0], [round(v,3) if v is not None else None for v in r[1:]])
# t-test: recent 6 vs prior 20 for each model
data = {k: [] for k in ['ic_reg10','ic_reg20','ic_reg40','ic_fusion']}
allrows = c.execute("""SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion
    FROM ic_daily ORDER BY signal_date DESC LIMIT 40""").fetchall()[::-1]
dates = [r[0] for r in allrows]
for i,k in enumerate(['ic_reg10','ic_reg20','ic_reg40','ic_fusion']):
    data[k] = [r[i+1] for r in allrows if r[i+1] is not None]
print('--- 6d mean vs 20d mean, t-test (recent6 vs prior14) ---')
for k,v in data.items():
    recent = v[-6:]; prior = v[-20:-6]
    m1, m2 = statistics.mean(recent), statistics.mean(prior)
    s1, s2 = statistics.stdev(recent), statistics.stdev(prior)
    se = math.sqrt(s1**2/len(recent) + s2**2/len(prior))
    t = (m1-m2)/se if se else 0
    print(f'{k}: recent6={m1:+.3f} prior14={m2:+.3f} t={t:+.2f}')
# rolling factor IC trend
print('--- factor_ic_roll last 10 ---')
cols2 = [r[1] for r in c.execute("PRAGMA table_info(factor_ic_roll)")]
print('roll cols:', cols2)
for r in c.execute("SELECT * FROM factor_ic_roll ORDER BY 1 DESC LIMIT 10"):
    print(r)