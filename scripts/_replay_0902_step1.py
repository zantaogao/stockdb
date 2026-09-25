# 回放V1: 重建8月策略账户卖出事件的触发类型（JSON导出层丢了reason，用流水+FIFO成本反推）
# 触发分类口径（strategy_accounts_daily.py 现行规则）:
#   R5硬止损: 卖价 <= 成本*0.88        加速止损: <=0.91      R7浮亏: <=0.94
#   回撤止盈: 卖价从峰值回撤>=阈值      窗口到期重建: 重评日整仓重建
#   其余 = 排名换仓(重评日出清)
import sqlite3, collections, json

c = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
trades = c.execute("""SELECT trade_date,trade_time,code,name,direction,price,quantity,strategy
                      FROM trade_log WHERE strategy!='main'
                      ORDER BY trade_date,trade_time,id""").fetchall()

# 期初持仓（08-03快照）作为初始批次
open_pos = c.execute("""SELECT account_id,code,shares,avg_cost,buy_date FROM strategy_positions""").fetchall()

# 只重放 2026-08-01 之后；8-01 之前的成交也要回放以建立成本，但只输出 8月+ 卖出
lots = collections.defaultdict(list)  # (aid,code) -> deque[shares,price]
# 用 08-03 期初+全部历史流水重建不精确（期初即08-03状态），改用：先重放全部流水建成本，
# 期初持仓作为 08-03 起点会重复 —— 简化：只用流水 FIFO，流水缺早期的按成本未知处理
events = []
first_seen = set()
for td, tt, code, name, dirn, px, qty, aid in trades:
    key = (aid, code)
    if dirn == 'BUY':
        lots[key].append([qty, px])
    else:  # SELL
        dq = lots[key]
        remain, cost_sum = qty, 0.0
        while remain > 0 and dq:
            lot = dq[0]
            take = min(remain, lot[0])
            cost_sum += take * lot[1]
            lot[0] -= take; remain -= take
            if lot[0] == 0: dq.pop(0)
        unknown = remain > 0
        if remain > 0:  # 成本未知部分（期初持仓）——用卖价近似成本? 不行，标记
            cost_sum += remain * float('nan')
        if unknown:
            avg_cost = None
        else:
            avg_cost = cost_sum / qty
        events.append(dict(date=td, time=tt, code=code, aid=aid, px=px, qty=qty,
                           avg_cost=avg_cost,
                           pnl_pct=None if avg_cost is None else round((px/avg_cost-1)*100, 2)))

aug = [e for e in events if e['date'] >= '2026-08-01']
have = [e for e in aug if e['pnl_pct'] is not None]
print('卖出事件 8月+:', len(aug), ' 成本可算:', len(have), ' 成本缺失(早期流水不全):', len(aug)-len(have))

# 分类
def classify(e):
    p = e['pnl_pct']
    if p is None: return '成本未知'
    if p <= -12: return 'R5硬止损(-12%以下)'
    if p <= -9: return '加速止损(-9~-12)'
    if p <= -6: return 'R7浮亏(-6~-9)'
    return '非止损卖出(止盈/重建/换仓)'

cnt = collections.Counter(classify(e) for e in aug)
for k, v in sorted(cnt.items(), key=lambda x:-x[1]): print(f'  {k}: {v}')
print()
# 按日分布（止损类）
stop_days = collections.Counter(e['date'] for e in aug if classify(e).startswith(('R5','R7','加速')))
print('止损类逐日:', dict(sorted(stop_days.items())))
json.dump(aug, open('analysis/replay_events_0902.json','w'), ensure_ascii=False)
print('已存 analysis/replay_events_0902.json')