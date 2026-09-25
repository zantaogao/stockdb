import json, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import fetch_prices_batch

# center_dual 当前持仓（09-24 09:36 建仓）
cd_pos = {'688659': ('元琛科技', 7500, 9.36), '003027': ('同兴科技', 4200, 16.56),
          '002875': ('安奈儿', 5300, 13.18), '300500': ('启迪设计', 7300, 9.59),
          '688607': ('康众科技', 1800, 38.91), '603382': ('海阳科技', 3700, 18.98),
          '300556': ('丝路视觉', 4300, 16.08), '300908': ('仲景食品', 4100, 17.16),
          '002942': ('新农股份', 2800, 17.01)}
codes = list(cd_pos)
live = fetch_prices_batch(codes)
orders = [
 {"action":"SELL","code":"605598","reason":"信号退出：未入今日候选池前15且浮盈仅+0.2%横盘占资金，让位高分候选"},
 {"action":"BUY","code":"603382","shares":3500,"reason":"中枢分-0.246候选池未持仓票最高，今日+0.6%非追高，套现后优先补买"},
 {"action":"BUY","code":"300500","shares":3500,"reason":"合成分98.09候选池第4，今日+1.5%非追高，中枢分未持仓票第3"},
 {"action":"BUY","code":"688659","shares":3200,"reason":"合成分98.86候选池第1，今日-0.3%非追高，剩余额度切入"},
 {"action":"BUY","code":"003027","shares":1000,"reason":"合成分98.56候选池第2，今日+0.2%非追高，扫尾补到近满仓"}
]
json.dump(orders, open('/tmp/agent_orders_202609241005.json','w'), ensure_ascii=False)
print('orders written')
