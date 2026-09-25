import sqlite3, os, glob, re

p = os.path.expanduser("~/.hermes/cron/executions.db")
c = sqlite3.connect(p)
q = """select e.id, e.job_id, j.name, e.status, e.started_at, e.finished_at, e.error
       from executions e left join (select distinct job_id from executions) x on x.job_id=e.job_id
       left join (select null as job_id, null as name) j on 0"""
# simpler: recent executions, look for intraday-ish job ids via jobs.json
rows = list(c.execute("select id, job_id, status, started_at, finished_at, error from executions order by id desc limit 40"))
for r in rows:
    print(r)
print("=== incidents ===")
for r in c.execute("select id, job_id, state, failure_type, first_seen_at, last_seen_at, substr(error,1,200) from cron_incidents order by id desc limit 20"):
    print(r)
