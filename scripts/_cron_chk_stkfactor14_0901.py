# Reproduce the decode error the cron scheduler saw. It tried to decode
# something whose byte 42 is 0xbc. Test candidate strings.
cands = {
    'script_path': 'backfill_stk_factor.sh',
    'script_path_abs': '/Users/zantao/.hermes/scripts/backfill_stk_factor.sh',
}
import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/cron/executions.db')
rows = c.execute("SELECT * FROM executions WHERE job_id='099aee371ab5' ORDER BY rowid DESC LIMIT 3").fetchall()
cols = [r[1] for r in c.execute("PRAGMA table_info(executions)")]
for r in rows:
    d = dict(zip(cols, r))
    for k, v in d.items():
        if isinstance(v, str):
            try:
                v.encode().decode('utf-8')
            except UnicodeDecodeError:
                print('field', k, 'fails')
    # check each str field's byte 42
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 42:
            b = v.encode()[42] if len(v.encode()) > 42 else None
            if b and b > 0x80:
                print(k, 'byte42=', hex(b), repr(v[:60]))

# Check the fire_claim and other fields in jobs.json
import json
jobs = json.load(open('/Users/zantao/.hermes/cron/jobs.json'))
jl = jobs if isinstance(jobs, list) else jobs.get('jobs', [])
for j in jl:
    if j.get('id') == '099aee371ab5':
        for k, v in j.items():
            if isinstance(v, str) and len(v.encode('utf-8')) > 42:
                b = v.encode('utf-8')[42]
                if b > 0x7f:
                    print('jobs.json field', k, 'byte42=', hex(b), repr(v[:70]))