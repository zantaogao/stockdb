"""RQAlpha 引擎闭环验证：①买入手数规则（200 股科创板/100 股整手）②T+1 拒单 ③成交价口径 vs 本地数据。"""
import os, pickle
os.environ.setdefault('RQALPHA_SKIP_VERSION_CHECK', '1')

def run_case(name, code, s, e, lots=100):
    src = f'''
from rqalpha.apis import *
def init(context):
    context.s = "{code}"
    context.fired = False
    context.rejected = []
def before_trading(context):
    logger.info("T+1 probe: try sell yesterday position")
    pos = context.portfolio.positions.get(context.s)
    if pos and pos.closable == 0 and pos.quantity > 0:
        o = order_target_percent(context.s, 0)
        logger.info("SELL_ORDER obj= %s" % (o,))
def handle_bar(context, bar_dict):
    if not context.fired:
        o = order_shares(context.s, {lots})
        logger.info("BUY_ORDER status=%s filled=%s avg=%s" % (o.status, o.filled_quantity, o.avg_price))
        context.fired = True
'''
    import io, contextlib
    from rqalpha import main as rq_main
    cfg = {
        'base': {'data_bundle_path': os.path.join(os.path.dirname(__file__), 'bundle'),
                 'start_date': int(s.replace('-','')), 'end_date': int(e.replace('-','')),
                 'frequency': '1d', 'accounts': {'stock': 1000000}},
        'mod': {'sys_analyser': {'enabled': True, 'plot': False},
                'sys_simulation': {'enabled': True, 'matching_type': 'current_bar'}},
        'extra': {'system_log': 'critical', 'user_log': 'critical'},
    }
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rq_main.run(cfg, source_code=src)
        except Exception as ex:
            print(name, 'RUN-FAIL:', repr(ex)[:200])
            return
    log = buf.getvalue()
    print('====', name, '====')
    for line in log.splitlines():
        if 'ORDER' in line or 'T+1' in line or 'reject' in line.lower() or 'error' in line.lower():
            print(' ', line[-120:])

if __name__ == '__main__':
    run_case('000001 整手买入', '000001.XSHE', '2025-04-08', '2025-04-10', 500)
    run_case('688 科创板 200股起', '688108.XSHG', '2025-04-08', '2025-04-10', 150)
