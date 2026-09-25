# ═══════════════════════════════════════════════
# Web 交易面板 (python3 trade.py 启动)
# ═══════════════════════════════════════════════

import os, sys, json, urllib.request
from datetime import datetime

HOLD_PATH = os.path.expanduser('~/.hermes/stockdb/holdings.json')
DB = os.path.expanduser('~/.hermes/stockdb/stock.db')

def load():
    with open(HOLD_PATH, encoding='utf-8') as f:
        return json.load(f)

def save(data):
    with open(HOLD_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def sina_code(code):
    if code in ('000001', '399001', '399006'):
        return {'000001': 'sh000001', '399001': 'sz399001', '399006': 'sz399006'}[code]
    return f'sh{code}' if code.startswith(('6','68')) else f'sz{code}'

def fetch_price(code):
    try:
        url = f"https://hq.sinajs.cn/list={sina_code(code)}"
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        raw = urllib.request.urlopen(req, timeout=5).read()
        text = raw.decode('gbk')
        if '=""' in text: return None
        parts = text.split('"')[1].split(',')
        return {'price': float(parts[3]), 'name': parts[0]}
    except:
        return None

def calc_stop(code, price):
    try:
        import duckdb
        conn = duckdb.connect(DB)
        rows = conn.execute(f"""
            SELECT high, low, close, LAG(close,1) OVER (ORDER BY date) as pc
            FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 15
        """).fetchall()
        trs = []
        for i in range(len(rows)-1):
            h, l, c = rows[i][0], rows[i][1], rows[i][2]
            pc = rows[i][3] or c
            trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        atr = sum(trs[:14]) / max(len(trs), 1)
        atr_pct = atr / price * 100 if price else 5
        sp = max(atr_pct*2, 6.67); sp = min(sp, 20.0)
        conn.close()
        return round(price*(1-sp/100), 2), round(sp, 1)
    except:
        return round(price*0.92, 2), 8.0

def cmd_buy(code, price_str, name=None):
    data = load()
    price = float(price_str)
    sl, sl_pct = calc_stop(code, price)
    today = datetime.now().strftime('%Y-%m-%d')
    found = next((p for p in data['positions'] if p['code']==code and p.get('status')=='watch'), None)
    if not found:
        found = next((p for p in data['positions'] if p['code']==code), None)
    if not found:
        found = {'code': code, 'name': name or code}
        data['positions'].append(found)
    found['status'] = 'hold'
    found['buy_date'] = today
    found['buy_price'] = price
    found['stop_loss'] = sl
    found['target'] = round(price*1.15, 2)
    found['note'] = f"买入 {today} ATR止损{sl_pct}%"
    save(data)
    return found

def cmd_sell(code, price_str):
    data = load(); price = float(price_str); today = datetime.now().strftime('%Y-%m-%d')
    for p in data['positions']:
        if p['code']==code and p.get('status') in ('hold','watch'):
            bp = p.get('buy_price')
            pnl = (price-bp)/bp*100 if bp else 0
            p['status']='sold'; p['sell_date']=today; p['sell_price']=price; p['pnl_pct']=round(pnl,2)
            p['note'] = f"{p.get('note','')} | 卖出 {today} {price}"
            save(data); return p

def cmd_add(code, price_str):
    data = load(); price = float(price_str); today = datetime.now().strftime('%Y-%m-%d')
    for p in data['positions']:
        if p['code']==code and p.get('status')=='hold' and p.get('buy_price'):
            old = p['buy_price']
            new_cost = round((old+price)/2, 2)
            sl, sl_pct = calc_stop(code, new_cost)
            p['buy_price']=new_cost; p['stop_loss']=sl; p['target']=round(new_cost*1.15,2)
            p['note'] = f"{p.get('note','')} | 补仓 {today} {price} 新成本{new_cost}"
            save(data); return p

HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>交易面板</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font: 14px Menlo, Monaco, monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
h2 { color: #00d4ff; margin: 20px 0 10px; }
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #333; }
th { color: #888; font-weight: normal; font-size: 12px; }
tr:hover { background: #16213e; }
.green { color: #00ff88; }
.red { color: #ff4466; }
.yellow { color: #ffd700; }
.gray { color: #666; }
.tag { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 11px; margin-right: 4px; }
.tag-hold { background: #00d4ff22; color: #00d4ff; }
.tag-watch { background: #ffd70022; color: #ffd700; }
.tag-sold { background: #666; color: #999; }
.form-row { display: flex; gap: 10px; margin: 10px 0; align-items: center; }
input, select, button { padding: 8px 12px; border: 1px solid #444; border-radius: 4px; background: #16213e; color: #e0e0e0; font: 14px Menlo, Monaco, monospace; }
button { cursor: pointer; background: #00d4ff33; border-color: #00d4ff; min-width: 60px; }
button:hover { background: #00d4ff55; }
button.danger { background: #ff446633; border-color: #ff4466; }
button.add { background: #00ff8833; border-color: #00ff88; }
.summary { display: flex; gap: 20px; margin-bottom: 20px; }
.card { background: #16213e; padding: 15px; border-radius: 8px; flex: 1; text-align: center; }
.card .num { font-size: 28px; font-weight: bold; }
.add { background:#ffa500; color:#fff; border:none; padding:2px 8px; border-radius:3px; cursor:pointer; font-size:12px; }
.modal-overlay { position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); z-index:1000; display:flex; align-items:center; justify-content:center; }
.modal { background:#1e1e1e; border-radius:8px; padding:24px; min-width:380px; max-width:500px; position:relative; border:1px solid #333; }
.modal h2 { margin:0 0 16px 0; font-size:18px; }
.modal table { width:100%; }
.modal table td { padding:6px 8px; border-bottom:1px solid #333; font-size:14px; }
.modal .close { position:absolute; top:12px; right:16px; font-size:24px; cursor:pointer; color:#888; }
.modal .close:hover { color:#fff; }
</style>
</head>
<body>
<div id="detail-modal"></div>
<h1>📊 交易面板</h1>

<div class="summary" id="summary"></div>

<h2>📌 持仓 (hold)</h2>
<table><thead><tr><th>代码</th><th>名称</th><th>现价</th><th>成本</th><th>盈亏</th><th>止损</th><th>目标</th><th>持有</th><th>操作</th></tr></thead>
<tbody id="hold-body"></tbody></table>

<h2>👁️ 观察 (watch)</h2>
<table><thead><tr><th>代码</th><th>名称</th><th>现价</th><th>介入区间</th><th>止损</th><th>操作</th></tr></thead>
<tbody id="watch-body"></tbody></table>

<h2>📋 已平仓 (sold)</h2>
<table><thead><tr><th>代码</th><th>名称</th><th>买入价</th><th>卖出价</th><th>盈亏</th><th>日期</th></tr></thead>
<tbody id="sold-body"></tbody></table>

<h2>➕ 手动操作</h2>
<div class="form-row">
  <select id="action"><option value="buy">买入</option><option value="sell">卖出</option><option value="add">补仓</option></select>
  <input id="code" placeholder="股票代码(6位)" size="10">
  <input id="price" placeholder="价格" size="8">
  <button onclick="doTrade()">执行</button>
</div>
<div id="result" style="margin-top:10px"></div>

<script>
let data = {};

async function load() {
  const r = await fetch('/api/holdings');
  data = await r.json();
  render();
}

async function doTrade() {
  const action = document.getElementById('action').value;
  const code = document.getElementById('code').value.trim();
  const price = document.getElementById('price').value.trim();
  if (!code) return;
  const r = await fetch('/api/trade', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action, code, price: price || '0'})
  });
  const result = await r.json();
  document.getElementById('result').innerHTML = result.ok
    ? `<span style="color:#0f0">${result.msg}</span>`
    : `<span style="color:#f44">${result.msg}</span>`;
  if (result.ok) { load(); document.getElementById('code').value = ''; document.getElementById('price').value = ''; }
}

function render() {
  const pos = data.positions || [];
  const hold = pos.filter(p => p.status === 'hold');
  const watch = pos.filter(p => p.status === 'watch');
  const sold = pos.filter(p => p.status === 'sold');

  // Summary
  let totalPnl = 0, wins = 0;
  sold.forEach(p => { if (p.pnl_pct) { totalPnl += p.pnl_pct; if (p.pnl_pct > 0) wins++; } });
  document.getElementById('summary').innerHTML =
    `<div class="card"><div class="num">${hold.length}</div>持仓</div>` +
    `<div class="card"><div class="num">${watch.length}</div>观察</div>` +
    `<div class="card"><div class="num">${sold.length}</div>已平仓</div>` +
    (sold.length ? `<div class="card"><div class="num ${totalPnl>=0?'green':'red'}">${totalPnl>=0?'+':''}${totalPnl.toFixed(1)}%</div>累计盈亏 | 胜率${(wins/sold.length*100).toFixed(0)}%</div>` : '');

  // Hold table
  document.getElementById('hold-body').innerHTML = hold.map(p => {
    const bp = p.buy_price || 0;
    const pnl = p._price ? ((p._price - bp) / bp * 100) : 0;
    const pnlClass = pnl >= 0 ? 'green' : 'red';
    const days = p.buy_date ? Math.floor((Date.now() - new Date(p.buy_date)) / 86400000) : 0;
    return `<tr style="cursor:pointer" onclick="showDetail('${p.code}')">
      <td>${p.code}</td><td>${p.name||''}</td>
      <td>${p._price||'?'}</td><td>${bp}</td>
      <td class="${pnlClass}">${pnl>=0?'+':''}${pnl.toFixed(1)}%</td>
      <td>${p.stop_loss||''}</td><td>${p.target||''}</td>
      <td>${days}天</td>
      <td>
        <button class="danger" onclick="event.stopPropagation();quickTrade('sell','${p.code}',${p._price||0})">卖出</button>
        <button class="add" onclick="event.stopPropagation();quickTrade('add','${p.code}',${p._price||0})">补仓</button>
      </td>
    </tr>`;
  }).join('');

  // Watch table
  document.getElementById('watch-body').innerHTML = watch.map(p => {
    return `<tr>
      <td>${p.code}</td><td>${p.name||''}</td>
      <td>${p._price||'?'}</td>
      <td>${p.entry_low||''} ~ ${p.entry_high||''}</td>
      <td>${p.stop_loss||''}</td>
      <td>
        <button onclick="quickTrade('buy','${p.code}',${p._price||0})">买入</button>
      </td>
    </tr>`;
  }).join('');

  // Sold table
  document.getElementById('sold-body').innerHTML = sold.map(p => {
    const pnlClass = (p.pnl_pct||0) >= 0 ? 'green' : 'red';
    return `<tr>
      <td>${p.code}</td><td>${p.name||''}</td>
      <td>${p.buy_price||''}</td><td>${p.sell_price||''}</td>
      <td class="${pnlClass}">${(p.pnl_pct||0)>=0?'+':''}${(p.pnl_pct||0).toFixed(1)}%</td>
      <td>${p.sell_date||''}</td>
    </tr>`;
  }).join('');
}

function quickTrade(action, code, price) {
  document.getElementById('action').value = action;
  document.getElementById('code').value = code;
  document.getElementById('price').value = price || '';
  document.getElementById('result').innerHTML = '';
  setTimeout(doTrade, 100);
}

async function showDetail(code) {
  const r = await fetch('/api/detail?code='+code);
  const d = await r.json();
  let h = '<div class="modal-overlay" onclick="closeDetail(event)"><div class="modal">';
  h += '<span class="close" onclick="closeDetail()">&times;</span>';
  if (d.error) { h += '<p>'+d.error+'</p>'; }
  else {
    h += '<h2>'+d.name+' ('+d.code+')</h2>';
    h += '<table><tr><td>现价</td><td class="'+(d.change>=0?'green':'red')+'">'+d.price+'</td>';
    h += '<td>涨跌</td><td class="'+(d.change>=0?'green':'red')+'">'+(d.change>=0?'+':'')+d.change+'%</td></tr>';
    h += '<tr><td>MA60</td><td>'+d.ma60+'</td><td>偏离</td><td class="'+(d.dev60>=0?'green':'red')+'">'+(d.dev60>=0?'+':'')+d.dev60.toFixed(1)+'%</td></tr>';
    h += '<tr><td>MA120</td><td>'+d.ma120+'</td><td>偏离</td><td class="'+(d.dev120>=0?'green':'red')+'">'+(d.dev120>=0?'+':'')+d.dev120.toFixed(1)+'%</td></tr>';
    h += '<tr><td>成交额</td><td>'+d.amount+'亿</td><td>量比</td><td>'+d.vol_ratio+'</td></tr>';
    h += '</table>';
    if (d.notes) { h += '<p style="margin-top:12px;color:#aaa;font-size:13px">'+d.notes+'</p>'; }
  }
  h += '</div></div>';
  document.getElementById('detail-modal').innerHTML = h;
}
function closeDetail(e) { if(!e||e.target.classList.contains('modal-overlay')) document.getElementById('detail-modal').innerHTML = ''; }

load();
setInterval(load, 60000);
</script>
</body>
</html>
"""


def web_server():
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/' or self.path == '/index.html':
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(HTML.encode())
            elif self.path == '/api/holdings':
                data = load()
                # 补价格：先用Sina实时，失败则用前日收盘
                for p in data.get('positions', []):
                    if p.get('status') in ('hold', 'watch'):
                        q = fetch_price(p['code'])
                        if q:
                            p['_price'] = q['price']
                        else:
                            # 盘后用DB前日收盘
                            try:
                                import duckdb
                                c = duckdb.connect(DB, read_only=True)
                                r = c.execute(f"SELECT close FROM stock_daily WHERE stock_code='{p['code']}' ORDER BY date DESC LIMIT 1").fetchone()
                                p['_price'] = float(r[0]) if r else None
                                c.close()
                            except:
                                p['_price'] = p.get('buy_price') or p.get('entry_low')
                self.send_json(data)
            elif self.path.startswith('/api/detail?'):
                from urllib.parse import parse_qs, urlparse
                params = parse_qs(urlparse(self.path).query)
                code = (params.get('code') or [''])[0]
                if not code:
                    self.send_json({'error':'缺少code参数'})
                else:
                    import duckdb
                    c = duckdb.connect(DB, read_only=True)
                    try:
                        name = c.execute(f"SELECT stock_name FROM stock_info WHERE stock_code='{code}'").fetchone()
                        name = str(name[0]) if name else code
                        row = c.execute(f"SELECT close, change_pct, amount, volume FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 1").fetchone()
                    except:
                        row = None
                    if not row:
                        self.send_json({'error':'暂无数据', 'code':code, 'name':name})
                    else:
                        close, chg, amt, vol = float(row[0]), float(row[1] or 0), float(row[2] or 0), float(row[3] or 0)
                        closes = [r[0] for r in c.execute(f"SELECT close FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 120").fetchall() if r[0]]
                        ma60 = sum(closes[:60])/min(60,len(closes)) if closes and len(closes)>=60 else 0
                        ma120 = sum(closes[:min(120,len(closes))])/min(120,len(closes)) if closes else 0
                        dev60 = (close-ma60)/ma60*100 if ma60 else 0
                        dev120 = (close-ma120)/ma120*100 if ma120 else 0
                        amt_yi = round(amt/1e8, 2) if amt else 0
                        vol_ratio = round(vol/(sum([r[0] for r in c.execute(f"SELECT volume FROM stock_daily WHERE stock_code='{code}' ORDER BY date DESC LIMIT 5 OFFSET 1").fetchall() if r[0]])/max(1,4-1)), 2) if vol else 0
                        # 查找持仓备注
                        holdings = load()
                        notes = ''
                        for p in holdings.get('positions',[]):
                            if p['code']==code and p.get('note'):
                                notes = p['note']
                                break
                        c.close()
                        self.send_json({
                            'code':code, 'name':name, 'price':close, 'change':round(chg,2),
                            'ma60':round(ma60,2), 'ma120':round(ma120,2),
                            'dev60':round(dev60,2), 'dev120':round(dev120,2),
                            'amount':amt_yi, 'vol_ratio':vol_ratio, 'notes':notes
                        })
            else:
                self.send_response(404); self.end_headers()

        def do_POST(self):
            if self.path == '/api/trade':
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                action = body.get('action', '')
                code = body.get('code', '')
                price = body.get('price', '0')

                try:
                    if action == 'buy':
                        cmd_buy(code, price)
                    elif action == 'sell':
                        cmd_sell(code, price)
                    elif action == 'add':
                        cmd_add(code, price)
                    self.send_json({'ok': True, 'msg': f'{action} {code} 完成'})
                except Exception as e:
                    self.send_json({'ok': False, 'msg': str(e)})
            else:
                self.send_response(404); self.end_headers()

        def send_json(self, data):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    port = 8090
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"\n📊 交易面板已启动 → http://localhost:{port}")
    print(f"   局域网访问 → http://192.168.3.118:{port}")
    print(f"   按 Ctrl+C 停止\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == '__main__':
    if len(sys.argv) > 2:
        # CLI 模式
        cmd = sys.argv[1]
        code = sys.argv[2]
        price = sys.argv[3] if len(sys.argv) > 3 else None

        if cmd == 'buy':
            cmd_buy(code, price)
        elif cmd == 'sell':
            cmd_sell(code, price)
        elif cmd == 'add':
            cmd_add(code, price)
        elif cmd == 'watch':
            cmd_watch_to_hold(code)
        else:
            print(f"用法: python3 trade.py buy|sell|add <code> [price]")
            print(f"      python3 trade.py watch <code>  # 按现价买入观察股")
            print(f"      python3 trade.py              # 启动Web面板")
    else:
        web_server()
