# 模拟交易系统 v2 - 单账户引擎

## 架构

```
单引擎 + 单账户 + 共享信号
```

## 目录结构

```
stockdb/
├── core/
│   ├── unified_account.py     # 统一账户模型（单账户main）
│   ├── signal_fetcher.py      # 统一信号层（解析combined_score输出）
│   ├── execution.py           # 执行引擎（价格+滑点+风控）
│   ├── sim_engine.py          # 统一交易引擎
│   ├── data_health.py         # 数据完整性校验
│   └── __init__.py
├── sim_accounts/              # 账户状态文件
│   └── main.json              # 中长线（100万）
├── scripts/
│   ├── run_trade_engine.py    # 每日交易引擎入口（cron调用）
│   ├── risk_check.py          # 盘中风控检查（cron每10分钟）
│   └── combined_score.py      # 信号计算（每日15:40）
├── server_dashboard.py        # 多账户Web面板（端口8081）
├── static/
│   └── dashboard.html         # Web面板前端
├── signals/                   # 每日信号缓存
├── models/                    # LightGBM模型
├── config.json                # 配置
├── tushare.db                 # 主力数据仓库 (DuckDB, 只读)
├── state.db                   # 业务状态库 (SQLite)
└── stock_basic.db             # 股票基本信息
```

## 使用方式

### 1. 运行交易引擎
```bash
# 每日盘后运行（cron: 15:40）
cd ~/.hermes/stockdb
python3 scripts/run_trade_engine.py

# 回测特定日期
python3 scripts/run_trade_engine.py --date 2026-06-23

# 只运行某个账户
python3 scripts/run_trade_engine.py --accounts main
```

### 2. 盘中风控检查
```bash
# 每10分钟运行一次（cron）
python3 scripts/risk_check.py
```

### 3. Web面板
```bash
# 启动Web面板
python3 server_multi_account.py --port 8081
# 访问: http://localhost:8081
```

### 4. 数据健康检查
```bash
python3 core/data_health.py
```

## 账户说明

| 账户 | 文件 | 资金 | 策略 |
|------|------|------|------|
| main | sim_accounts/main.json | 100万 | 中长线，信号驱动 |

> 旧 multi-account (short/sim) 配置已移除，仅保留 main 单账户。

## Cron 调度建议

```bash
# 每日15:40 运行交易引擎
40 15 * * 1-5 cd /Users/zantao/.hermes/stockdb && python3 scripts/run_trade_engine.py >> /tmp/stockdb_engine.log 2>&1

# 每10分钟风控检查（交易时段）
*/10 10-15 * * 1-5 cd /Users/zantao/.hermes/stockdb && python3 scripts/risk_check.py >> /tmp/stockdb_risk.log 2>&1

# 每日17:00 生成日报
0 17 * * 1-5 cd /Users/zantao/.hermes/stockdb && python3 scripts/run_trade_engine.py --report >> /tmp/stockdb_report.log 2>&1
```

## 迁移说明

旧 multi-account 配置已清理，仅保留 main 单账户。
旧版文件（account.json 等）保留为兼容副本。
