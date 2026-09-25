#!/usr/bin/env python3
"""盘前外盘/资讯采集器（无梯子国内直连，全部已实测）
输出 analysis/premarket_data.txt 并打印。供盘前报告 cron agent 作数据底稿。
数据源：
  - tushare pro index_global: 美股三大/港股/日经/韩/英/德（国内API，无需梯子）
  - akshare 东财 futures_global_spot_em: COMEX黄金铜/美债期货/原油（重试2次）
  - akshare 东财 index_global_spot_em: 全球指数实时（重试2次，含美元指数）
  - akshare sina fx_spot_quote: 离岸/在岸人民币
  - akshare sina/ths 快讯: 隔夜财经要闻（代替 web_search 的资讯部分）
铁律：任何一源失败不中断，标注「未获取」继续下一源。
"""
import sys, io, time, json, os, traceback
os.environ['TQDM_DISABLE'] = '1'
from pathlib import Path
from datetime import datetime, timedelta

BASE = Path('/Users/zantao/.hermes/stockdb')
OUT = BASE / 'analysis/premarket_data.txt'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sec = []
def log(s=''):
    sec.append(s)

def retry(fn, n=3, wait=2, name=''):
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            if i == n - 1:
                log(f"  [{name}] 获取失败({type(e).__name__}: {str(e)[:80]}) — 未获取")
                return None
            time.sleep(wait)

now = datetime.now()
today = now.strftime('%Y%m%d')
log(f"=== 盘前外盘数据 {now.strftime('%Y-%m-%d %H:%M')} ===")

# ---------- 1. tushare index_global 外盘指数 ----------
try:
    import tushare as ts
    cfg = json.load(open(BASE / 'config.json'))
    ts.set_token(cfg['tushare_token'])
    pro = ts.pro_api()
    start = (now - timedelta(days=10)).strftime('%Y%m%d')
    idx_map = [('DJI','道指'), ('IXIC','纳指'), ('SPX','标普500'), ('HSI','恒生指数'),
               ('N225','日经225'), ('KS11','韩国综合'), ('FTSE','英国富时100'), ('GDAXI','德国DAX')]
    log()
    log("【外盘指数·tushare index_global】(最近两个交易日)")
    for code, cn in idx_map:
        df = retry(lambda c=code: pro.index_global(ts_code=c, start_date=start, end_date=today), name=f'index_global {code}')
        if df is None or df.empty:
            continue
        df = df.sort_values('trade_date').tail(2)
        last = df.iloc[-1]
        line = f"  {cn}({code}): {last['close']:.2f}"
        if last['pct_chg'] is not None:
            line += f" {last['pct_chg']:+.2f}%"
        line += f"  [{last['trade_date']}]"
        if len(df) > 1:
            line += f"  前一日 {df.iloc[0]['close']:.2f} ({df.iloc[0]['pct_chg']:+.2f}%)"
        log(line)
        time.sleep(0.3)
except Exception:
    log("【外盘指数】整体失败：\n" + traceback.format_exc(limit=2))

# ---------- 2. 东财全球指数实时（含美元指数，可能间歇拒连） ----------
try:
    import akshare as ak
    log()
    log("【全球指数实时·东财spot】")
    df = retry(lambda: ak.index_global_spot_em(), name='index_global_spot_em')
    if df is not None:
        want = df[df['名称'].str.contains('美元指数|道琼斯|纳斯达克|标普|日经|恒生|富时|DAX|法国CAC', na=False)]
        for _, r in want.iterrows():
            log(f"  {r['名称']}: {r['最新价']} 涨跌{r['涨跌幅']}% [{r['最新行情时间']}]")
except Exception:
    log("【全球指数实时】失败：" + traceback.format_exc(limit=1))

# ---------- 3. 隔夜美股明星股/中概（sina 日线，映射A股板块用） ----------
try:
    import concurrent.futures as _cf
    log()
    log("【隔夜美股个股·sina日线】(隔夜涨跌幅，A股映射参考)")
    syms = ['NVDA','MSFT','AAPL','TSLA','META','GOOG','AMZN','AVGO','MU','TSM','ASML','INTC','AMD',
            'BABA','KWEB','XPEV','NIO','LI']
    def _us_one(s):
        try:
            df = ak.stock_us_daily(symbol=s)
            r = df.tail(2)
            pct = (r.iloc[-1]['close']/r.iloc[-2]['close']-1)*100 if len(r) > 1 else float('nan')
            return f"  {s}: {r.iloc[-1]['close']} {pct:+.2f}% [{str(r.iloc[-1]['date'])[:10]}]"
        except Exception as e:
            return f"  {s}: 未获取({type(e).__name__})"
    with _cf.ThreadPoolExecutor(6) as ex:
        for line in ex.map(_us_one, syms):
            log(line)
except Exception:
    log("【美股个股】失败：" + traceback.format_exc(limit=1))

# ---------- 4. 东财期货（黄金/铜/原油/美债/A50） ----------
try:
    log()
    log("【外盘期货·东财spot】")
    df = retry(lambda: ak.futures_global_spot_em(), name='futures_global_spot_em')
    if df is not None:
        keys = ['COMEX黄金', 'COMEX铜', '伦敦金', '伦敦铜', '布伦特原油', 'NYMEX原油']
        hit = df[df['名称'].isin(keys)]
        # A50期指当月连续 = 富时中国A50夜盘，直接指示A股开盘倾向
        a50 = df[df['名称'].str.contains('A50期指当月连续', na=False)]
        # 美债用当月连续价格（价格与收益率反向）
        bond = df[df['名称'].str.contains('10年美国债当月连续|2年美国债当月连续', na=False)]
        for _, r in hit.iterrows():
            log(f"  {r['名称']}: {r['最新价']} 涨跌{r['涨跌幅']}% (昨结{r['昨结']})")
        for _, r in a50.iterrows():
            log(f"  ★{r['名称']}: {r['最新价']} 涨跌{r['涨跌幅']}% (昨结{r['昨结']}) — 夜盘价直接指示A股开盘倾向")
        for _, r in bond.iterrows():
            log(f"  {r['名称']}: {r['最新价']} 涨跌{r['涨跌幅']}%（注意：期货价格与收益率反向）")
        crude = df[df['名称'].str.contains('原油当月连续|迷你原油当月', na=False)]
        for _, r in crude.iterrows():
            log(f"  {r['名称']}: {r['最新价']} 涨跌{r['涨跌幅']}%")
except Exception:
    log("【外盘期货】失败：" + traceback.format_exc(limit=1))

# ---------- 4. 人民币 ----------
try:
    log()
    log("【汇率·sina】")
    df = retry(lambda: ak.fx_spot_quote(), name='fx_spot_quote')
    if df is not None:
        for pair in ['USD/CNY', 'EUR/CNY', 'JPY/CNY', 'GBP/CNY']:
            row = df[df['货币对'].astype(str).str.contains(pair.replace('100',''), na=False)]
            if len(row):
                r0 = row.iloc[0]
                log(f"  {r0['货币对']}: 买{r0['买报价']} 卖{r0['卖报价']}")
except Exception:
    log("【汇率】失败：" + traceback.format_exc(limit=1))

# ---------- 5. 快讯（sina + 同花顺，去重合并） ----------
try:
    log()
    log("【隔夜快讯】(北京时间，新→旧，sina+同花顺合并去重)")
    items = []
    df1 = retry(lambda: ak.stock_info_global_sina(), name='global_sina')
    if df1 is not None:
        for _, r in df1.iterrows():
            t = str(r.get('时间', '')); txt = str(r.get('内容', '')).strip().replace('\n', ' ')
            if txt: items.append((t, txt, 'sina'))
    df2 = retry(lambda: ak.stock_info_global_ths(), name='global_ths')
    if df2 is not None:
        for _, r in df2.iterrows():
            t = str(r.get('发布时间', '')); txt = str(r.get('内容', '')).strip().replace('\n', ' ')
            if txt: items.append((t, txt, 'ths'))
    seen = set(); uniq = []
    for t, txt, src in sorted(items, key=lambda x: x[0], reverse=True):
        k = txt[:30]
        if k in seen: continue
        seen.add(k); uniq.append((t, txt, src))
    for t, txt, src in uniq[:40]:
        log(f"  [{t}][{src}] {txt[:160]}")
except Exception:
    log("【快讯】失败：" + traceback.format_exc(limit=1))

text = '\n'.join(sec)
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(text, encoding='utf-8')
print(text)
print(f"\n>>> 已存 {OUT}")