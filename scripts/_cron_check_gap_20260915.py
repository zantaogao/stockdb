import sqlite3, os
c = sqlite3.connect(os.path.expanduser('~/.hermes/cron/executions.db'))
cols = [r[1] for r in c.execute("PRAGMA table_info(executions)")]
print("=== all 051af215dc32 rows claimed 2026-09-15 ===")
for r in c.execute("SELECT claimed_at,status,error,delivery_outcome,scheduled_instant FROM executions WHERE job_id='051af215dc32' AND claimed_at LIKE '2026-09-15%' ORDER BY claimed_at"):
    print("  ", r)
print("=== all jobs claimed 10:30-10:40 today ===")
for r in c.execute("SELECT job_id,claimed_at,status,error FROM executions WHERE claimed_at>='2026-09-15T10:30' AND claimed_at<'2026-09-15T10:41' ORDER BY claimed_at"):
    print("  ", r)
print("=== count by job today ===")
for r in c.execute("SELECT job_id, COUNT(*) FROM executions WHERE claimed_at LIKE '2026-09-15%' GROUP BY job_id ORDER BY 2 DESC"):
    print("  ", r)
c.close()
