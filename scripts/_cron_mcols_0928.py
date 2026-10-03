import sqlite3
con = sqlite3.connect('file:/Users/zantao/.hermes/state.db?mode=ro', uri=True)
cols = [c[1] for c in con.execute('pragma table_info(messages)')]
print(cols)
