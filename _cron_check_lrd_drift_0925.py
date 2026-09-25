# 对拍 sim_accounts/*.json 派生层 lrd 是否与 ledger.db 权威源一致（09-25 修复1核查）
import json, sqlite3, glob, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
s = sqlite3.connect('ledger.db')
db_lrd = {}
for a, cfg in s.execute("SELECT account_id, config_json FROM strategy_accounts_meta"):
    db_lrd[a] = str(json.loads(cfg or '{}').get('last_rebalance_date') or '')
for f in sorted(glob.glob('sim_accounts/*.json')):
    aid = os.path.basename(f)[:-5]
    if aid not in db_lrd:
        continue
    j = json.load(open(f))
    j_lrd = str(j.get('config', {}).get('last_rebalance_date') or '')
    flag = 'OK' if j_lrd.replace('-','') == db_lrd[aid].replace('-','') else 'DRIFT'
    print(f"{flag:6s} {aid:15s} db={db_lrd[aid]} json={j_lrd}")
