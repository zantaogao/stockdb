# stockdb 架构底账（v1 定稿 2026-09-25，三方对账收敛：本Agent初版 + DeepSeek 审查 + 其量化补充）

## 0. 基线冻结（2026-09-25 三方实测复现）
- core/ = 24 模块 6900 行（逐文件：sim_engine 950、executor 655、unified_account 610、features 603、data_source 576、scoring 503、execution 364、db_safe 293、scoring_v8 265、trade_log 257、account 241、signal_fetcher 229、db 226、defense 178、derived_export 161、prices 136、data_health 131、db_lock 123、engine_risk_monitor 112、trade_calendar 105、signal_store 102、hold_days 53、trading_time 27、__init__ 0）
- scripts/ 942 个 .py（_ 前缀一次性 668）；server_dashboard.py 1987 行；agents/exec_agent.py 796 行
- 库：tushare.db 65G（DuckDB）、tdx_archive.db 25G、indicators.db 2G、signals.db 349M、factors.db 112M、ledger.db 408K（SQLite）、db_backups/ 205G
- cron/jobs.json 56 条（enabled 53）；7 条带"交易日历硬闸"（2026-09-25 上线）
- 收益度量基线（迁移后对照）：可删行数≈2579（一期 1714+二期 865）、0918 类锁冲突≥2 次（09-18/09-21）、日历类 bug 1 起（0925 休市日误单+假 NAV）、trade_calendar 105 行补丁

## 1. 分层账（11 层）
| 层 | 模块/规模 | 自研 or 外部件 | 理由 |
|---|---|---|---|
| 数据接入 | data_source 576、signal_fetcher 229、prices 136 | 自研 | 三源（tushare/pytdx/新浪）已按我方口径捏合；AkShare 仅候选回填源 |
| 存储 | db/db_safe/db_lock 642 | 架构自研 | SQLite 账本+DuckDB 行情分库已拍板；治理并发纪律而非换软件 |
| 特征/评分/融合 | features 603、scoring 503、scoring_v8 265 | 自研 IP | fusion 融合公式与 reg10 独立线是核心 IP；Qlib 仅 DSL 参考 |
| 模型训练 | 12 个 LightGBM .txt（96M）；PC 训练 Mac 推理 | 引擎已是开源件 | MLflow 后置（阶段4+）买可查性 |
| 执行/撮合 | exec_agent 796+executor 655+execution 364 | **迁 RQAlpha（一期）** | 0925 休市日误单=手搓层无日历概念的又一例；停牌至今无数据；引擎级内置 |
| 账户/风控/账务 | unified_account 610、account 241、trade_log 257 | **迁 RQAlpha（二期，可选）** | "漏账户"整类 bug 结构性消失 |
| defense 状态机 | defense 178（0916 拍板，mode 存 ledger.db defense_state 单行表） | **策略 IP，进 strategy 钩子保留** | 人工拍板仓位逻辑，不随账户层迁（归类纠正 2026-09-25） |
| 回测/仿真 | sim_engine 950、replay/ | 引擎迁 RQAlpha | sim_engine 是其简化重复发明；replay 结论留数据不留引擎 |
| 统计/绩效 | nav 9 文件 287 行+报告绩效段≈500-800 | quantstats | 绩效报告段；IC 33 文件 3774 行系因子分析→alphalens-reloaded/Qlib（Alphalens 原版停更） |
| 调度 | cron 56 条 | cron 不换 | 只补"上游完成断言"编排依赖链（Prefect 全迁已否） |
| 展示/报告 | server_dashboard 1987+LLM 日报（7 页 PDF 硬模板） | 自研保留 | 面板数字护栏+/api/dashboard 是真实资产；LLM 报告层无外部替代 |
| 日历/合规 | trade_calendar 105、trading_time 27 | 自研 | 0925 刚建 |

## 2. 替换量化（RQAlpha）
- 一期（执行/撮合）：可删 sim_engine 950+execution 364+executor 撮合段估 400 ≈1714 行 → RQAlpha 引擎+matcher（涨跌停/停牌/T+1/量限）+slippage+order
- 二期（账本/账户）：可删 unified_account 610+executor 余段估 255 ≈865 行 → portfolio+position+account
- 保留 IP：defense 178+13 处止损/止盈引信 → strategy 钩子（知识落位映射表见 §3）
- 新增成本：数据源对接+strategy 钩子 估 300~600 行；净减≈2000-2300 行。真收益≠行数：休市/停牌/除权/T+1 引擎级内置。

## 3. 知识落位映射表（13 处引信 ↔ RQAlpha strategy 钩子，Task 3.3 填写）
| # | 规则 | 代码位置 | 钩子段落 | 状态 |
|---|---|---|---|---|
| 1-13 | （逐条，含阈值与触发逻辑，对照 DECISIONS/OPS_FACTS 溯源） | | 待填 | 待建 |
- bar 时间戳口径（Task 2.2 锁死）：baostock 5min = bar-结束口径（实测 603257 0923 首根标签 20260923093500000，09:30 bar 覆盖 09:30–09:35 标签 09:35）。RQAlpha 适配须同口径转换。

## 4. 锁冲突根因账（0918/0921 事故，2026-09-25 结案分析）
- 持锁者：scripts/update_etf.py:26/31 可写 duckdb.connect + INSERT fund_daily/fund_basic——**合法 writer**（v2 纪律内置：core/db_lock.tushare_write_lock(timeout=600)；.sh 头注释"必须用 PATH python3（有 tushare）"）。
- 受害者：refresh 46176067da46（17:30 主账户收盘快照）。台账：DECISIONS.md:162/189、OPS_FACTS.md:50；持锁 25min（executions.db 两日均 24-25min）。
- 处方定案：错峰 ETF 17:20→17:50（read_only 处方作废——它就是要写）；可选二期压缩持锁段（攒批一次写）。
- 旁证同层病灶：面板 8081 已自带 read_only+抖动重试（09-17 修"锁冲突致当日收益降级为 0"）；可写连接纪律外另有 3 处待处置（swap_fin_rebuild.py:77、pc_final_train_v5.py:23、backfill_tdx_2015.py:25；final_compare.py 开 stock.db 不涉案）。

## 5. 五问定案（2026-09-25）
① 锁冲突=错峰 17:50+可选压锁 ② exec_agent 留壳+ENGINE=rqalpha|legacy 秒级开关 ③ stockdb 单仓库（0925 硬闸即跨 core+4 脚本，分仓必陷版本对齐）④ 模型不进 git，models/MANIFEST.txt（文件名+sha256+训练日期+指标+样本集）⑤ 920 补拉=cron 自动重试+缺失数入健康检查（连续 7 天>0 推 QQ）。

## 6. 双机定位
过渡期 M2=只读镜像：禁止独立修改、跟随本机单向同步；已分叉不并账（代码差 3 模块/700 行、v2 vs state.db，09-11 拍板"不并账"为长期状态）。

## 7. 执行纪律
9:30-15:00 不动生产脚本（前置断言+pre-commit hook）；改动前 .bak 全文；jobs.json 改前备份且验证闸数=7；影子链禁止双写 ledger.db（只读我方数据→对拍→切权威）；切权威时报告链与交易链口径同步（0925 假 NAV 即口径分裂同类）。
