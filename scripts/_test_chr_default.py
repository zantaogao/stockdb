import sqlite3, os
p = '/Users/zantao/.hermes/stockdb/scripts/_test_chr.db'
if os.path.exists(p): os.remove(p)
c = sqlite3.connect(p)
try:
    c.execute("CREATE TABLE t(a TEXT, created_at TEXT DEFAULT (datetime(chr(39)+chr(110)+chr(111)+chr(119)+chr(39), chr(39)+chr(108)+chr(111)+chr(99)+chr(97)+chr(108)+chr(116)+chr(105)+chr(109)+chr(101)+chr(39))))")
    c.execute("INSERT INTO t(a) VALUES ('x')")
    print("insert ok", c.execute("SELECT * FROM t").fetchall())
except Exception as e:
    print("ERR:", type(e).__name__, e)
os.remove(p)