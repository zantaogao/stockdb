-- holdings 表重建 v2（0927 审计）：UNIQUE(code,status) + INSERT OR IGNORE 幂等 + 数据直接从备份库带入
-- 备份库 /tmp/ledger.db.bak_pre0927audit 已 ATTACH；其中 301110 有 3 行，OR IGNORE 只保第一行（三行内容逐列相同）
BEGIN;
CREATE TABLE holdings_v (
  "code" TEXT,
  "name" TEXT,
  "status" TEXT,
  "buy_date" TEXT,
  "avg_cost" REAL,
  "shares" INTEGER,
  "latest_price" REAL,
  "pnl" REAL,
  "pnl_pct" REAL,
  "update_time" TEXT,
  target_price REAL,
  stop_loss REAL,
  UNIQUE(code, status)
);
ATTACH '/tmp/ledger.db.bak_pre0927audit' AS bak;
INSERT OR IGNORE INTO holdings_v SELECT code,name,status,buy_date,avg_cost,shares,latest_price,pnl,pnl_pct,update_time,target_price,stop_loss FROM bak.holdings;
DROP TABLE holdings;
ALTER TABLE holdings_v RENAME TO holdings;
COMMIT;
DETACH bak;
