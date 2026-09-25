# 量化模型改进计划

## 当前状态

### 模型架构
- **20d回归**: `lgb_reg_20d_tushare_v13_opt.txt` (54树, 29维特征)
- **40d回归**: `lgb_reg_40d_new_stkfactor.txt` (500树, 29维特征)
- **10d回归**: `lgb_reg_10d_tushare_v1.txt` (30树, 35维特征) — 已训练但未接入
- **评分方式**: 百分位排名 (v8_score = 20d原始预测值)

### 当前管线
```
features.py (38维) → scoring.py (26维+3因子=29维) → LightGBM 20d/40d
                                        ↓
                                signal_agent.py → state.db signal_history
                                        ↓
                                server_multi_account.py → Web Dashboard
```

### 已发现问题
1. **7月14日评分NULL**: 最新评分记录 reg20/reg40/reg10 全是 NULL — scoring.py 模型预测返回了 None
2. **10d模型未接入**: `reg10` 永远是 0，有现成的 `lgb_reg_10d_tushare_v1.txt` 和 stats 但未使用
3. **GTJA评分全零**: 有数据管道但 `gtja_score` 全是 0
4. **因子IC表为空**: `factor_ic_roll` 无数据
5. **20d模型树少**: 54棵树 vs 40d的500棵，区分度可能不够

---

## 改进项 (按优先级)

### P0: 修复评分 NULL Bug

**问题**: 7月14日新评分的 reg20/reg40 全是 NULL
**根因**: scoring.py 模型预测返回 None，signal_agent.py 没做容错处理
**修复**:
1. 在 scoring.py 的 `score_stock` 中，当模型预测失败时返回默认值而不是 None
2. 在 signal_agent.py 的保存逻辑中，确保 NULL 不进入数据库

**预估工作量**: 15分钟

### P1: 接入 10d 模型

**现状**: reg10 硬编码为 0
**改进**:
1. scoring.py 加载 `lgb_reg_10d_tushare_v1.txt`
2. 使用 `v6_norm_stats_10d_tushare_v1.json` 做标准化 (35维)
3. 注意: 10d模型用35维(stats)，20d用29维 — 需要对齐特征集
4. signal_agent.py 中 reg10 不再写死 0

**预估工作量**: 30分钟

### P2: 因子 IC 计算

**现状**: `factor_ic_roll` 表为空
**改进**:
1. 计算每个因子的 IC、ICIR、胜率
2. 每批评分后自动更新 `factor_ic_roll`
3. 覆盖所有因子: 价格类、成交量类、技术指标类

**预估工作量**: 1小时

### P3: 20d 模型重训练

**现状**: 54棵树，区分度有限
**改进**:
1. 增加树数到 300-500 (与40d对齐)
2. 增加 early_stopping 耐心值
3. 在 tushare.db 全量数据上重训
4. 交叉验证评估 RMSE/MAE/R²

**预估工作量**: 2小时 (含回测验证)

### P4: GTJA 评分接入

**现状**: gtja_score 全为 0
**改进**:
1. 检查 GTJA 数据是否可用
2. 接入 GTJA 评分逻辑到 scoring.py
3. 融合 GTJA 到最终评分

**预估工作量**: 45分钟

### P5: 回测框架

**现状**: 无系统化回测
**改进**:
1. 自动回测脚本: 按评分分组 → 计算未来N日收益 → 对比大盘
2. 输出: 夏普比率、信息比率、最大回撤
3. 每周自动运行一次

**预估工作量**: 1.5小时

---

## 执行顺序

建议先做 P0 → P1 → P2，其他后续。

## 验证标准

每次改进后必须验证:
1. `/api/signals` 返回数据完整 (reg20/reg40/reg10 非 NULL)
2. 回测区分度: 高分组-低分组 > 3%
3. 相关性: 评分 vs 实际收益 r > 0.25
4. 前端观察名单正常渲染
5. Web Dashboard 个股分析页面正常
