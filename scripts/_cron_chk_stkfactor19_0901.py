import sqlite3, glob, hashlib, os

# 1) today's signal chain state
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
d = '20260901'
print('fusion_center today:', sig.execute("SELECT COUNT(*) FROM fusion_center_signals WHERE REPLACE(trade_date,'-','')=?", [d]).fetchone()[0])

# 2) lock files / WAL
print('locks:', [os.path.basename(f) for f in glob.glob('/Users/zantao/.hermes/stockdb/*.lock*')])
print('tushare wal:', glob.glob('/Users/zantao/.hermes/stockdb/*.wal'))

# 3) binary files with byte42 == 0xbc (GBK-style mojibake candidates modified today)
hits = []
for f in glob.glob('/Users/zantao/.hermes/scripts/*') + glob.glob('/Users/zantao/.hermes/stockdb/scripts/backfill*'):
    if os.path.isfile(f):
        b = open(f, 'rb').read(200)
        if len(b) > 42 and b[42] == 0xbc:
            try:
                b.decode('utf-8')
            except UnicodeDecodeError:
                hits.append(f)
                print('HIT:', f, b[30:60])
print('binary-at-42 files:', hits)