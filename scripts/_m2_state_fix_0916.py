#!/usr/bin/env python3
"""2026-09-16 修复：把 sim_accounts/*.json 里今日'手动碎仓清理'流水补进 state.db。
权威源=sim_accounts JSON（M2 DB-first 未迁移，JSON 为事实源）；state.db 只是面板显示层。
幂等：同 (trade_date, code, strategy, 'SELL') 已存在则跳过。改前已有 state.db.bak.20260916_fix。"""
import json, glob, os, sqlite3, datetime

BASE = os.path.expanduser('~/.hermes/stockdb')
DB = os.path.join(BASE, 'state.db')
TODAY = '2026-09-16'
NOW_TS = datetime.datetime.now().strftime('%H:%M:%S')
N = 0

db = sqlite3.connect(DB)

def has(date, code, strat):
    return db.execute("SELECT 1 FROM trade_log WHERE trade_date=? AND code=? AND strategy IS ? AND direction='SELL'",
                      (date, code, strat)).fetchone() is not None

for f in sorted(glob.glob(BASE + '/sim_accounts/*.json')):
    if '.bak' in os.path.basename(f):
        continue
    d = json.load(open(f))
    aid = d.get('id') or os.path.basename(f)[:-5]
    if aid == 'main':
        aid = ''          # 主账户在 trade_log 里 strategy 为 NULL/''
    for t in d.get('trades', []):
        if str(t.get('date', '')).replace('-', '') != '20260916':
            continue
        if '手动碎仓清理' not in str(t.get('reason', '')):
            continue
        strat = aid or None
        if has(TODAY, t['code'], strat):
            print(f'  跳过(已存在) {aid or "main"} {t["code"]}')
            continue
        db.execute("""INSERT INTO trade_log
            (code,name,direction,price,quantity,amount,trade_date,trade_time,strategy,signal_score,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (t['code'], t['name'], 'SELL', t['price'], t['shares'], t['amount'],
             TODAY, t.get('trade_time', NOW_TS) if False else NOW_TS, strat, None, t.get('reason', '')))
        N += 1
        print(f'  补 {aid or "main"} SELL {t["code"]} {t["name"]} {t["shares"]}股 @{t["price"]}')

# holdings 对齐权威 JSON（仅主账户：面板 holdings 读 state.db）
main = json.load(open(BASE + '/sim_accounts/main.json'))
json_codes = {p['code'] for p in main['positions']}
db_codes = {r[0] for r in db.execute("SELECT code FROM holdings")}
for stale in sorted(db_codes - json_codes):
    name = db.execute("SELECT name FROM holdings WHERE code=?", (stale,)).fetchone()
    db.execute("DELETE FROM holdings WHERE code=?", (stale,))
    print(f'  删陈旧持仓 {stale} {name[0] if name else ""}')
for missing in sorted(json_codes - db_codes):
    p = next(x for x in main['positions'] if x['code'] == missing)
    db.execute("""INSERT INTO holdings (code,name,status,buy_date,avg_cost,shares,update_time)
                  VALUES (?,?,'hold',?,?,?,?)""",
               (p['code'], p['name'], p.get('buy_date', ''), p['avg_cost'], p['shares'], NOW_TS))
    print(f'  补持仓 {p["code"]} {p["name"]} {p["shares"]}股')
# 现金对齐
if db.execute("SELECT 1 FROM account_balance").fetchone():
    db.execute("UPDATE account_balance SET cash_balance=?, last_update=?", (main['cash'], NOW_TS))
    print(f'  现金对齐: {main["cash"]:,.2f}')
else:
    print('  (state.db 无 account_balance 表，跳过现金)')

db.commit()
chk = db.execute("SELECT COUNT(*) FROM trade_log WHERE trade_date=? AND notes LIKE '手动碎仓%'", (TODAY,)).fetchone()[0]
print(f'DONE 补入{N}笔 | state.db 今日碎仓清理流水共{chk}笔 | holdings {db.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]}只')
db.close()
