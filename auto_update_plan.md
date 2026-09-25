# 全自动选股评分 + 个股每日跟踪 — 设计方案

## 一、全自动选股评分加入观察名单

新建 `auto_update_watch.py`，盘后17:35自动执行：

```
复盘.py --mode long → 候选列表
        ↓
scoring.py 逐股评分 → 筛选得分≥75的TOP5
        ↓
读取 holdings.json → 判断是否已在watch/已持仓（去重）
        ↓
新候选加入 watch（记录加入日期 watch_added）
        ↓
记录每日快照到 stock_tracking.json
        ↓
同步 simulate.py 账户
```

## 二、个股每日跟踪数据

新建 `stock_tracking.json`，结构：

```json
{
  "001288": {
    "name": "运机集团",
    "watch_added": "2026-05-14",
    "daily": [
      {
        "date": "2026-05-14",
        "close": 29.0,
        "change_pct": 3.5,
        "volume_ratio": 1.2,
        "score": 85.0,
        "money_flow": 12500000,
        "ma5": 28.2,
        "ma20": 26.5,
        "ma60": 25.0,
        "ma120": 23.8,
        "note": "放量突破MA60，评分85"
      }
    ]
  }
}
```

每日快照在 `auto_update_watch.py` 执行时追加，数据来源：
- close/change: 从 stock_daily 表取
- ma系列: 从 stock_daily 计算
- score: 从 scoring.py 结果
- money_flow: 从 money_flow 表取
- volume_ratio: 当日量/20日均量

## 三、个股详情页（simulate.py 新增）

**API**: `GET /api/stock_detail/<code>` 返回：
```json
{
  "code": "001288",
  "name": "运机集团",
  "status": "hold",
  "watch_added": "2026-05-14",
  "buy_date": "2026-05-14",
  "buy_price": 29.0,
  "current_price": 32.16,
  "pnl_pct": 10.9,
  "daily_snapshots": [ ... ],
  "trades": [ ... ]
}
```

**详情页** 点击股票代码跳转，展示：
1. 顶部卡片 — 代码/名称/状态/持有天数/盈亏
2. 价格走势图 — Canvas折线，标注买入点/止损位/目标位
3. 每日数据表 — 日期|收盘|涨跌%|量比|评分|主力资金|MA5|MA20|MA60|备注
4. 相关操作 — 买入/卖出/更新净值

## 四、时间线

- 15:30 — 日线数据更新（已存在 cron）
- 17:30 — 复盘总结（已存在 cron，LLM驱动）
- **17:35 — auto_update_watch.py 执行 → 候选入观察 → 记录快照**
- 17:36 — simulate.py 净值更新

## 五、文件改动

| 文件 | 操作 |
|---|---|
| 新建 `scripts/auto_update_watch.py` | 自动化管线 |
| 新建 `stock_tracking.json` | 每日快照存储 |
| 修改 `scripts/simulate.py` | 新增详情API+页面 |
