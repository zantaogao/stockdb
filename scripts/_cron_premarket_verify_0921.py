#!/usr/bin/env python3
# 盘前2.5核验：持仓+榜内票 5日涨幅/距20日高/连涨 + 美股个股/汇率兜底
import duckdb, sqlite3, urllib.request, json, ssl

CODES = {
 # 主账户持仓
 '301237.SZ':'和顺科技','001332.SZ':'锡装股份','688191.SH':'智洋创新','301093.SZ':'华兰股份',
 '688093.SH':'世华科技','301283.SZ':'聚胶股份','300658.SZ':'延江股份','301590.SZ':'优优绿能',
 '601615.SH':'明阳智能','002454.SZ':'松芝股份','603202.SH':'天有为','600076.SH':'康欣新材',
 '688186.SH':'广大特材','603966.SZ':'法兰泰克','301110.SZ':'青木科技','605598.SH':'上海港湾',
 # 榜内拟点名票
 '301575.SZ':'艾芬达','301233.SZ':'盛帮股份','688081.SH':'兴图新科','300970.SZ':'华绿生物',
 '603811.SH':'诚意药业','688377.SH':'迪威尔','688399.SH':'硕世生物','301042.SZ':'安联锐视',
 '000923.SZ':'河钢资源','002405.SZ':'四维图新','300442.SZ':'润泽科技','000155.SZ':'川能动力',
 '300651.SZ':'金陵体育','688335.SH':'复洁科技','301503.SZ':'智迪科技','600791.SH':'京能置业',
 '688356.SH':'键凯科技','600103.SH':'青山纸业','300328.SZ':'宜安科技','300839.SZ':'博汇股份',
 '002491.SZ':'通鼎互联','688503.SZ':'聚和材料','300864.SZ':'南大环境','003018.SZ':'金富科技',
}
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('=== 日线核验（截至最近交易日）===')
print('code 名称 | 最近5日收盘涨幅% | 距20日高% | 近3日逐日% | 最近交易日%')
for ts, name in CODES.items():
    rows = db.execute("""
        SELECT trade_date, close, pct_chg FROM daily
        WHERE ts_code=? ORDER BY trade_date DESC LIMIT 21""", [ts]).fetchall()
    if len(rows) < 6:
        print(f'{ts} {name} | 数据不足'); continue
    rows = rows[::-1]  # 升序
    closes = [r[1] for r in rows]
    last5 = (closes[-1]/closes[-6]-1)*100
    hi20 = max(closes[-21:-1]) if len(closes)>=21 else max(closes[:-1])
    to_hi = (closes[-1]/hi20-1)*100
    last3 = [round(r[2],2) for r in rows[-3:]]
    print(f'{ts} {name} | 5日{last5:+.1f}% | 距20日高{to_hi:+.1f}% | 近3日{last3} | 末日{rows[-1][2]:+.2f}% ({rows[-1][0]})')
db.close()

print()
print('=== 美股个股兜底·sina gb_ ===')
tickers = 'gb_nvda,gb_msft,gb_aapl,gb_tsla,gb_meta,gb_goog,gb_amzn,gb_avgo,mu,gb_tsm,gb_asml,gb_intc,gb_amd,baba,kweb,xpev,nio,li'.split(',')
# sina: gb_ 前缀全部
q = ','.join('gb_'+t for t in tickers)
try:
    req = urllib.request.Request(f'https://hq.sinajs.cn/list={q}', headers={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'})
    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    data = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode('gbk')
    for line in data.strip().split('\n'):
        try:
            var, rest = line.split('=',1)
            f = rest.strip('";').split(',')
            sym = var.split('_')[-1].upper()
            if len(f) > 3:
                print(f'{sym}: {f[1][:12]} 现价{f[1] if False else f[2]} 涨跌{f[4]}% 日期{f[3] if len(f)>3 else "?"}')
        except Exception:
            pass
except Exception as e:
    print('美股行情获取失败:', repr(e))

print()
print('=== 汇率兜底·sina fx ===')
try:
    req = urllib.request.Request('https://hq.sinajs.cn/list=fx_susdcny,fx_seurcny,fx_sgbpcny,fx_sjpycny', headers={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'})
    ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    data = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode('gbk')
    print(data.strip())
except Exception as e:
    print('汇率获取失败:', repr(e))
