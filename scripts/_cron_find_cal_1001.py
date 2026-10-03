import duckdb, glob, os
for db in sorted(glob.glob("/Users/zantao/.hermes/stockdb/**/*.db*", recursive=True)):
    if not os.path.isfile(db):
        continue
    try:
        con = duckdb.connect(db, read_only=True)
        tabs = [t[0] for t in con.sql("select table_name from information_schema.tables").fetchall()]
        hits = [t for t in tabs if "trade_cal" in t or t == "calendar"]
        if hits:
            print(db, hits)
        con.close()
    except Exception as e:
        pass
