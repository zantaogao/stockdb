-- 回滚 holdings 重建：恢复原始表结构（无 UNIQUE），从 holdings_v 搬回全部数据
BEGIN;
CREATE TABLE holdings_restore (
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
  stop_loss REAL
);
INSERT INTO holdings_restore SELECT * FROM holdings;
DROP TABLE holdings;
ALTER TABLE holdings_restore RENAME TO holdings;
COMMIT;
