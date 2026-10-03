import duckdb, os
home = os.path.expanduser("~/.hermes")
con = duckdb.connect(os.path.join(home, "stockdb/signals.db"), read_only=True)
tabs = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
print("tabs:", tabs)
con.close()
