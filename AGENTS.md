# A-Quant 交易系统操作手册（AGENTS.md）

本文件在 stockdb 目录下工作时自动加载。模型开窗即可知道系统结构，无需全系统查找。

## 接管章程（09-02 用户授权：全权操作）

**授权范围**——以下事项 agent 直接决策+执行，不做事前请示：
1. 运维：管线故障重跑/补拉、明显 bug 修复、cron 任务健康处置（遵守：改前备份、一次一参数、幂等重跑）
2. 研究：按既有统计判据自动执法——IC 哨兵触发重训、回测显著性达标才切换、权重调整须 t 检验显著。样本不足宁可等，不拍板
3. 规则/阈值：agent 制定方案并实施，但**生效前必须在 DECISIONS.md 留一条含依据+回滚方法的记录**，用户保留事后叫停权

**硬边界（不可自主）**：**删除任何文件/任务必须用户同意（09-03 用户立规，覆盖一切授权）**、入金出金/资金总量、动 tushare.db/state.db 写入、交易时段外发起真实交易。

**决策日志**：每次自主改动追加一行到 `~/.hermes/stockdb/DECISIONS.md`，格式：
`| 日期 | 层(运维/研究/规则) | 改了什么 | 依据(数据/判据) | 回滚方法 |`
23:55 综合报告须包含"今日自主决策"一节（读 DECISIONS.md 当日行）；当日无记录则写"无自主决策"。

**工程事实档案**：存储/信号/模型/交易规则/cron 的全部细节在 `~/.hermes/stockdb/OPS_FACTS.md`（09-03 起为唯一细节源）。新的状态类结论写这里或对应 skill，禁止写进 agent 记忆索引层。

## 系统概述

- 路径: `/Users/zantao/.hermes/stockdb`
- 数据库: `tushare.db`（DuckDB，**只读**，禁止写入）+ v2 三层存储（2026-08-29 起）：`ledger.db`（热层账本，可写：holdings/trade_log/account_balance/watchlist/strategy_*/position_peaks）+ `signals.db`（温层信号，可写：signal_history/fusion_3f_*/new_factors/*_ic*/tdx_*）。`state.db` 已冻结只读（历史源，勿写入）。连接入口：`core/db.py` 的 `connect_ledger()` / `connect_signals()` / `get_state_db()`（=ledger 本体 + ATTACH signals AS sig，非限定表名自动跨库）
- 主 skill: `aquant-pipeline`（完整方法论，遇到交易任务先加载它）
- 面板: `server_dashboard.py` :8081（launchd `com.aquant.dashboard` 常驻）

## 数据库速查

| 库 | 表 | 说明 |
|----|----|------|
| tushare.db | daily | 日线行情，trade_date 是 YYYYMMDD VARCHAR |
| tushare.db | daily_basic | 估值，circ_mv 单位=万元（/1e4=亿） |
| tushare.db | stk_factor | 因子（直接列全 0，真实值在 extra JSON _bfq 键） |
| tushare.db | fin_income / fin_balancesheet / fin_cashflow | 财报（85/152/97 列，主键 ts_code+end_date） |
| tushare.db | stock_basic | 股票列表，列是 ts_code（state.db 旧版才是 stock_code） |
| signals.db | signal_history | 信号，date 混 YYYYMMDD/YYYY-MM-DD，stock_code 混裸码/带后缀 |
| signals.db | fusion_3f_signals | 三因子融合信号（0-100 分，百分位分级） |
| signals.db | ic_daily | 模型 IC（signal_date 主键） |
| signals.db | factor_ic_roll | 因子滚动 IC（win_rate 存小数 0-1） |
| ledger.db | holdings | 持仓（**唯一权威源**） |
| ledger.db | account_balance | 账户现金（**唯一权威源**） |

**铁律**: 查询日期统一 YYYYMMDD，不在 SQL 里加 REPLACE。持仓/账户只认 ledger.db，不认 JSON 文件。跨库查询用 get_state_db()（信号表可带 sig. 前缀或裸名自动解析）。

## 关键脚本

| 脚本 | 作用 | 运行时间 |
|------|------|---------|
| scripts/update_tushare_api.py | 数据增量更新（原子交换） | cron 16:00 |
| scripts/compute_indicators_daily.sh | 技术指标自算（SELF_IND 双轨） | cron 16:10 |
| scripts/update_etf.py | ETF 净值 | cron 17:20 |
| scripts/backfill_stk_factor.sh | stk_factor 补拉 + 信号链（signal_agent→new_factors→fusion_3f→fusion_center） | cron 22:00 |
| new_factors.py + fusion_3f_engine.py（stockdb根目录） | 三因子融合（22:00 补拉链内联执行） | — |
| scripts/backtest_fusion.sh / backtest_cmmr.sh | 三因子/CMMR 等权回测 | cron 19:10 / 19:20 |
| scripts/daily_audit.sh | 每日账目对账 | cron 19:30 |
| scripts/backup.sh | 全系统备份 | cron 19:45 |
| scripts/etf_scoring.sh | ETF 全市场评分 | cron 23:20 |
| scripts/ic_daily.sh / cmmr_ic_daily.sh | IC 监控 | cron 23:35 / 23:50 |
| scripts/intraday_decision.py | 盘中决策（13 处止损） | 盘中 5-12 分钟 |
| agents/exec_agent.py | 订单执行（读 pending.json） | 盘中 |

**⚠️ 脚本必须用 PATH python3**（有 tushare 1.4.29），不要用 /usr/bin/python3 或 venv python。

## 模型

| 模型 | 文件 | 树数 |
|------|------|------|
| 10d v8 | models/lgb_reg_10d_v8.txt | —（0927 上线，见 OPS_FACTS/fusion 链） |
| 20d v2 | models/lgb_reg_20d_v2.txt | 融合中剔除（字段照落库观察） |
| 40d v8 | models/lgb_reg_40d_v8.txt | —（0927 上线） |

融合权重: reg10×25% + reg40×75%（scoring.py line 371，0927 v8 上线定档；reg20 剔除出融合、字段照落库观察。旧 8/3 权重 reg10×20%+reg20×30%+reg40×50% 废止）。
重训前必须备份模型+stats（.bak 后缀），重训后校准 0.03 阈值。

## Cron 依赖链

16:00 数据更新 → 16:10 指标自算 → 17:20 ETF 净值 → **17:50 主账户收盘快照刷新**（`refresh_main_snapshot.sh`，估值不交易；09-23 起从 17:30 挪来——update_etf 实测跑 25 分钟持 tushare.db 写锁到 ~17:45，17:30 必撞锁）→ 18:15 均值回归 → 19:45 备份 → 22:00 stk_factor 补拉+信号链（signal_agent→new_factors→fusion_3f→fusion_center）→ 22:05 双轨对比 → 23:20 ETF 评分 → 23:35 IC → 23:50 CMMR IC。（08-25 起信号链并入 22:00 补拉链；18:20/30/35 独立信号 cron 已停）
所有批处理 cron 已转 LLM 模式（跟随当前模型）。盘中决策/下单是 no_agent。

## 常见操作

```bash
# 查最新交易日
python3 -c "import duckdb; print(duckdb.connect('tushare.db', read_only=True).execute('SELECT MAX(trade_date) FROM daily').fetchone()[0])"

# 查持仓
python3 -c "import sqlite3; c=sqlite3.connect('ledger.db'); print(c.execute('SELECT * FROM holdings').fetchall())"

# 重启面板（改代码后）
launchctl kickstart -k gui/$(id -u)/com.aquant.dashboard

# 健康检查
python3 -B scripts/health_verify.py
```

## 已知陷阱（详见 aquant-pipeline skill）

- tushare.db 只读铁律：任何写入走临时库+原子交换
- signal_history 双格式：查询用 REPLACE(date,'-','') 排序
- 账户唯一源 ledger.db：不允许 holdings.json 双轨
- 主账户 trade_log 自 **2026-07-20** 起才有记录（7/7 建仓 16 笔买入、8/4~8/14 丢的 SELL 不在表内）→ 现金/总资产/面板不受影响，但月报平仓统计、报告流水条数只含有完整配对的部分；对账第 8 节 nightly 记未配对笔数（`logs/main_fifo_gap.log`，**增量才告警**；本机基线 6 笔）
- 主账户账本只在**有成交的执行轮**刷新价格 → 17:50 cron 补一次收盘估值（复用 `exec_agent.sync_to_db`，results 空=只估值不成交；09-23 从 17:30 挪到 17:50 避开 update_etf 的 tushare.db 写锁）；判成交价异常**不能用当日收盘**，系统按盘中实时价成交（300806 8/19 开盘 52.53 卖、收 46.78 属正常）
- 评分链路历史回算必须传 as_of_date（防未来数据泄漏）
- 改 cron prompt 里的解释器路径 = 风险操作
