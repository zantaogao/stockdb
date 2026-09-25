import sqlite3, os, collections
c = sqlite3.connect(os.path.expanduser('~/.hermes/cron/executions.db'))
print("=== 051af215dc32 runs per day (last 10 days) ===")
d = collections.Counter()
for (ca,) in c.execute("SELECT claimed_at FROM executions WHERE job_id='051af215dc32'"):
    d[ca[:10]] += 1
for k in sorted(d)[-10:]:
    print("  ", k, d[k])
print("=== other 10-min jobs runs per day (last 4 days) ===")
for jid in ('2e55e47d3ccd','e26411bc653e','5128c85c245a'):
    d = collections.Counter()
    for (ca,) in c.execute("SELECT claimed_at FROM executions WHERE job_id=?", (jid,)):
        d[ca[:10]] += 1
    print("  ", jid, {k: d[k] for k in sorted(d)[-4:]})
c.close()
