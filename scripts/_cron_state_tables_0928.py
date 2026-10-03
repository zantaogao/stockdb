import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
tbls = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
print(tbls)
