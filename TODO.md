# 待办

## [2026-09-04] RQAlpha 可行性验证 — 等分钟线回填完成后开工
背景：手搓交易层太简陋（JSON 账本、自写除权脚本今天才发现漏账户、停牌是盲区）。
交易域模型直接用开源成熟货：RQAlpha（米筐，6745 star，最后 commit 2026-08-28 活跃维护，
停牌/除权/T+1/撮合限制引擎级内置）。已拍板：今晚 backfill_min5 跑完并验收后开工。

步骤（本机做，不碰 M2；验证好一段时间再谈同步）：
1. pip 装 rqalpha，跑通自带示例策略
2. minutes/5min/ Parquet 接成 RQAlpha 自定义数据源（tushare→rqalpha 有社区先例）
3. 603257 案例回放：现行 exec_agent 规则改写成 RQAlpha strategy，
   回测成交价 vs ledger.db 实际成交（09:30@66.90 买 / 09:30:31@61.99 卖）对齐 — 可行性验收标准
4. 跑通后写进 OPS_FACTS，评估二期：账本层是否迁到它的 portfolio 模型
   （ca_adjustments/audit 闭环若建在其账户模型上，"漏账户"整类 bug 结构性消失）

验收前提（回填完成后先做）：
- 清点入库只数 + failed.txt 补拉
- 抽 603257/605028 等票，分钟线 bar 价格区间覆盖 ledger.db 成交价

## 状态
- [ ] 回填完成并验收
- [ ] rqalpha 示例跑通
- [ ] 603257 回放对齐 ledger.db