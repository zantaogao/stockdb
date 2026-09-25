import json
orders = [
 {"action":"BUY","code":"300500","shares":5000,"reason":"合成分98.09候选池第4，中枢分未持仓票第3，测试现金边界"},
 {"action":"BUY","code":"688659","shares":3000,"reason":"合成分98.86候选池第1，非追高，测试现金边界"},
]
json.dump(orders, open('/tmp/agent_orders_boundary.json','w'), ensure_ascii=False)
print('ok')
