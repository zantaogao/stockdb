# CMMR IC监督 (23:50 tick) 核查结论 — 2026-09-23夜

## 结论：链路本身正常（脚本静默=正常），但有1个跨job写锁事故待处置 + 1个信号级预警

## 1. etf_scores FAIL（健康检查唯一红项）— 根因已实锤，属22:15 ETF job，与23:50 CMMR链无关
- 22:15:42 etf_scoring.py 全量重评 2347 只，45s 跑完 2300/2347（已评分1516、错误0），
  最后 `save_etf_scores()` 一次性写 signals.db 时抛 `sqlite3.OperationalError: database is locked` exit=1，
  **1516 条评分全部丢失（未 commit，无部分落库）**。
- 根因：22:00 stk_factor补拉链(099aee371ab5)尾部的 fusion_3f_engine.py 22:11:58 才进写阶段
  （DELETE+批量INSERT 大事务，持 signals.db 写锁到约22:18，>30s），etf_scoring 连接 timeout=30 等满即崩。
  证据链：fusion_3f_signals 09-23 自身 4982 条写入成功（同一把锁，一方成功一方阵亡）。
- 当前锁状态：`ls tushare.db.new` 无、`lsof signals.db` 无持有者 → 锁已释放，可补跑。
- etf_scores 现止于 2026-09-22（1516条）；etf_ic 止于 signal_date=20260922（IC -0.0309, n=1854）。
  **欠账：09-23 的 ETF 评分+etf_ic 缺一天**，补跑 `bash scripts/etf_scoring.sh`（约1分钟）即可，
  本 tick 按禁写规则未动手。
- 结构性建议（择日改）：save_etf_scores 分批 commit + busy_timeout 提到 120s；或 ETF 评分挪 22:40 错开 22:00 链。

## 2. CMMR 1日IC 连续负 — 数据真实、计算正确，是 regime 现象非 bug
- cmmr_ic_daily 最新：09-22 IC=-0.2085 (win_rate 0.264, fd=1)；fusion_ic_daily 09-22 IC=-0.0851 (0.276)。
- 独立复算证实数字真实（/tmp/_cmmr_regime.py，signal_history.cmmr_score × tushare.db daily 次日收益）：
  09-22 的 1日 IC 复算约 -0.077~-0.208 区间为真，09-23 反转为 +0.218。
- 8/4~9/23 共37个信号日的1日IC在 ±0.3 间震荡、无持续符号 → 短线方向 IC 本就是噪声主导。
- 1日IC与大盘宽度强相关：市场跌日（涨家<50%）高分池尾部10只相对市场中位超额显著差于涨日
  （Welch t=-2.34, p=0.026）。即连续负IC=近两日跌市里高分票跑输，属已知模式，非数据/管线故障。
- 定稿10d窗（cmmr_ic_daily forward_days=10）30个定稿日 mean IC≈-0.017，无显著正向；
  top10轨近40日 excess_pool 均值+0.27%/日、win率50%，近10日 excess_pool -0.45%——CMMR短线轨近期无显著alpha，
  与 fusion（0.2reg10+0.3reg20+0.5reg40 轨）拉开差距，符合"短线cmmr分量近周失效"的判断。

## 3. 附带小项
- scripts/ 下有个 0 字节 `signals.db` 假库（22:15 job 的 agent 用相对路径+cwd=scripts 误建）。
  无害但任何 cwd=scripts 的相对路径连接会静默写进它。按删除须批准规则未清，待用户示下。

## 待用户拍板（本 tick 均未动手，遵守禁改码/禁写库/禁重启）
1. 是否补跑 `etf_scoring.sh` 补 09-23 的 ETF 评分（否则明天 etf_ic/patrol 继续报缺）。
2. 结构性修复（分批commit+busy_timeout 120s，或错峰到22:40）是否排期。
3. scripts/signals.db 空壳是否删除。
