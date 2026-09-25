# -*- coding: utf-8 -*-
# 新浪API拉全市场耗时实测（2026-09-20 周日休市测；延迟量级与交易时段可比，
# 盘中服务端生成快照更慢一点，故此处是下界估计）
# 档1: 实时快照批量 hq.sinajs.cn/list= 一批N票（URL长度限~2000字符 → 每批约80票）
# 档2: 全市场5分钟分时逐票 sina money_flow 分时接口 scale=5，并发8/16线程
import duckdb, time, requests
from concurrent.futures import ThreadPoolExecutor

HDR = {'Referer': 'https://finance.sina.com.cn'}
BASE = '/Users/zantao/.hermes/stockdb'

codes = [r[0][:6] for r in duckdb.connect(BASE + '/tushare.db', read_only=True).execute(
    "select ts_code from daily where trade_date='20260918' and ts_code not like '%.BJ'").fetchall()]
print('全市场票数:', len(codes))

def prefix(c):
    if c[0] in '69': return 'sh' + c
    if c[0] in '48': return 'bj' + c
    return 'sz' + c
syms = [prefix(c) for c in codes]

# ---- 档1: 快照批量 ----
def batch_time(batch_n, workers):
    batches = [syms[i:i+batch_n] for i in range(0, len(syms), batch_n)]
    def one(b):
        r = requests.get('https://hq.sinajs.cn/list=' + ','.join(b), headers=HDR, timeout=10)
        assert r.status_code == 200
        return len(r.content), r.text.count('hq_str_')
    t0 = time.time()
    tot = nrec = 0
    with ThreadPoolExecutor(workers) as ex:
        for n, k in ex.map(one, batches):
            tot += n; nrec += k
    dt = time.time() - t0
    print('快照 批%03d 并发%d: %.1fs 请求%d票 返回%d条 %dKB' % (batch_n, workers, dt, len(syms), nrec, tot//1024))
    return dt

batch_time(80, 8)
batch_time(80, 16)
batch_time(40, 16)

# ---- 档2: 5分钟分时逐票 ----
def one_min5(s):
    u = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
         'CN_MarketData.getKLineData?symbol=%s&scale=5&ma=no&datalen=48' % s)
    r = requests.get(u, headers=HDR, timeout=10)
    return len(r.content)

def minute5_time(sample, workers):
    sub = syms[:sample]
    t0 = time.time()
    ok = fail = 0
    with ThreadPoolExecutor(workers) as ex:
        for n in ex.map(lambda s: (lambda: 0)() or _try(s), sub):
            ok += (n > 0); fail += (n == 0)
    dt = time.time() - t0
    print('5min分时 %d票 并发%d: %.1fs (成功%d 失败%d), 全市场5300票外推≈%.0fs' % (
        sample, workers, dt, ok, fail, dt / sample * 5300))
    return dt

def _try(s):
    try:
        return one_min5(s)
    except Exception:
        return 0

minute5_time(200, 16)
minute5_time(200, 32)
minute5_time(200, 64)
print('DONE')
