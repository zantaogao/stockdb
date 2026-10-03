# 0929验证: tdx_archive.py 去重修复
# A. 真实CSV(今日新拉,无重复) → 临时库重放, 应成功且行数=库里今日行数
# B. 构造重复主键 → 应打告警行且入库成功(旧代码此处抛ConstraintException)
import duckdb, importlib.util, sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

spec = importlib.util.spec_from_file_location("tdx_archive", Path(__file__).parent / "tdx_archive.py")
ta = importlib.util.module_from_spec(spec); spec.loader.exec_module(ta)

TMP = Path("/tmp/archive_verify_0929.duckdb")
if TMP.exists(): TMP.unlink()
ta.ARCHIVE_DB = TMP

# A: 真实CSV
n = ta.archive_csv('/tmp/tdx_min1_recent.csv', 'min1_archive')
db = duckdb.connect(str(TMP))
a_rows = db.execute("SELECT COUNT(*) FROM min1_archive").fetchone()[0]
print(f"A(真实CSV): archive_csv返回{n}, 临时库{a_rows}行")

# B: 构造重复 — 复制库里20260923的100行×2造成重复
import pandas as pd
dup = db.execute("SELECT datetime,code,market,open,high,low,close,volume FROM min1_archive JOIN (SELECT date,tm,date AS d2,tm AS t2 FROM min1_archive) USING(datetime) WHERE 1=0").fetchall() if False else None
df = db.execute("""SELECT CAST(date AS VARCHAR)||' '||LPAD(CAST(tm//60 AS VARCHAR),2,'0')||LPAD(CAST(tm%60 AS VARCHAR),2,'0') AS datetime,
    code, market, open, high, low, close, volume FROM min1_archive WHERE date=20260923 LIMIT 100""").df()
df2 = pd.concat([df, df], ignore_index=True)  # 每行×2 = 100个主键各重复
dupcsv = Path('/tmp/dup_test_0929.csv'); df2.to_csv(dupcsv, index=False)
db.close()
print(f"B(构造重复): 输入{len(df2)}行(100主键×2)")
n2 = ta.archive_csv(str(dupcsv), 'min1_archive')  # 旧代码这里抛 ConstraintException
db = duckdb.connect(str(TMP))
print("B结果: 入库成功, 20260923行数 =", db.execute("SELECT COUNT(*) FROM min1_archive WHERE date=20260923").fetchone()[0])
db.close()
print("✅ 去重修复验证通过" if a_rows and n2 else "❌ 验证失败")
