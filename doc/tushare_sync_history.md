# Tushare 数据同步记录

## 2026-06-27 完整同步

### 问题
- `tushare.db` 损坏（5.3GB），从 M2(192.168.3.188) 拷贝完整备份（7.8GB）
- 财务数据停在 2026Q1（3/31），需要更新到最新

### 改动

#### 1. `scripts/update_tushare_api.py` — Tushare API 增量更新
- 拉取所有 tushare 表（daily, daily_basic, adj_factor, stk_limit, moneyflow, index_daily）
- 增量模式：只拉比本地新的数据
- 限速：500 req/min

#### 2. `scripts/update_financials.py` — 财务数据 API 更新
- 每只股票逐个查询 income/balancesheet/cashflow
- 后台运行，~5500只×3表×100次=16500次API调用
- 约50分钟完成

#### 3. `scripts/sync_tushare_data.py` — Tushare → Stock 同步
新增：
- `sync_financials()`: 把 tushare 的 fin_income/fin_balancesheet/fin_cashflow 同步到 stock.db 的 `stk_fin_income`/`stk_fin_balancesheet`/`stk_fin_cashflow`
  - 列名带引号（可能含特殊字符）
  - 每列需要显式指定类型 VARCHAR（DuckDB 的 PRAGMA table_info 获取类型，DESCRIBE 拿不到）
- `sync_valuation()`: 把 daily_basic 同步到 `stock_valuation` 表

⚠ 关键坑：
- `fin_income` 表名在 ATTACH tushare 时有命名冲突 → 用 `stk_` 前缀
- CREATE TABLE 每列必须带类型（VARCHAR），不能只写列名
- PRAGMA table_info 返回 (cid, name, type, notnull, dflt, pk)，用这个获取列类型

#### 4. `agents/signal_agent.py` — 选股过滤
- `SCORE_THRESHOLD`: 25 → 65
- `TOP_N`: 200 → 30  
- `get_all_stocks()`: 新增过滤无财务数据、无估值数据的股票
  - 从 `stk_fin_income` 查有财务数据的股票集合
  - 从 `stock_valuation` 查有估值数据的股票集合
  - 排除不在两个集合中的股票

#### 5. `core/signal_fetcher.py`
- `SignalFetcher.fetch()` 默认参数: top_n 200→30, min_score 25→65

### 当前数据状态 (2026-06-27)
- stock_daily: 8,551,225 条，最新 2026-06-26
- stock_info: 5,530 只
- stock_valuation: 14,753,803 条 (PE/PB/PS)
- stk_fin_income: 293,311 条
- stk_fin_balancesheet: 263,177 条
- stk_fin_cashflow: 286,693 条
- adj_factor: 11,933,623 条
- money_flow_full: 11,059,695 条
- stk_limit: 13,763,339 条

### 下次更新流程
1. `python3 scripts/update_tushare_api.py` — 拉最新数据到 tushare.db
2. `python3 scripts/update_financials.py` — 拉最新财务数据（后台，~50分钟）
3. `python3 scripts/sync_tushare_data.py` — 同步到 stock.db
4. 不需要重启 server_multi_account.py
