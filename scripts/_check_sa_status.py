import duckdb, sqlite3, glob, os
base = os.path.expanduser("~/.hermes/stockdb")
for db in sorted(set(glob.glob(base+"/**/*.db", recursive=True)+glob.glob(base+"/**/*.duckdb", recursive=True))):
    try:
        head = open(db,'rb').read(16)
        if b'SQLite' in head:
            con = sqlite3.connect(db); cur=con.cursor()
            tabs=[r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            q = lambda s: cur.execute(s).fetchall()
        else:
            con = duckdb.connect(db, read_only=True)
            tabs=[r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()]
            q = lambda s: con.execute(s).fetchall()
        hits=[t for t in tabs if 'strateg' in t.lower() or 'nav' in t.lower()]
        if hits:
            print("DB:", db, hits)
            for t in hits:
                try:
                    cols=[c[1] for c in q(f"PRAGMA table_info('{t}')")] if b'SQLite' in head else [c[1] for c in con.execute(f"PRAGMA table_info('{t}')").fetchall()]
                    print("  ", t, cols)
                except Exception as e:
                    print("  ", t, "ERR", e)
        con.close()
    except Exception:
        pass
