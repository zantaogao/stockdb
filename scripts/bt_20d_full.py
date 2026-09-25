#!/usr/bin/env python3
"""20d模型回测 — 与新模型+新特征管线完全一致

策略：每月第一个交易日，用模型预测全市场，选评分最高的N只等权重买入，持有20日。
"""
import json, sys, time, math
import numpy as np
import lightgbm as lgb
from pathlib import Path
from collections import OrderedDict

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.features import compute_raw_features, standardize_v5, _load_index_cache
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
MODEL_DIR = BASE / 'models'
DB_PATH = BASE / 'stock.db'
FWD_DAYS = 20
TOP_N = 10          # 选前N只
INITIAL_CAP = 1000000
TEST_START = '2025-01-01'
COMMISSION = 0.0003  # 万3
SLIPPAGE = 0.005    # 0.5%


def load_model():
    model = lgb.Booster(model_file=str(MODEL_DIR / 'lgb_reg_model.txt'))
    norm_stats = {}
    ns_path = MODEL_DIR / 'v6_norm_stats.json'
    if ns_path.exists():
        with open(ns_path) as f:
            norm_stats = json.load(f)
    return model, norm_stats


def apply_norm(feat, norm_stats):
    for j in range(min(len(feat), 37)):
        key = f'feat_{j}'
        if key in norm_stats and norm_stats[key]['std'] > 0:
            s = norm_stats[key]
            feat[j] = max(feat[j], s['low'])
            feat[j] = min(feat[j], s['high'])
            feat[j] = (feat[j] - s['mean']) / s['std']
    return feat


def predict_one(code, target_date, conn, model, norm_stats, gtja_data, gtja_names_list):
    """对一只股票一天做预测"""
    rows = conn.execute(f"""
        SELECT date, close, open, high, low, change_pct, volume, amount
        FROM stock_daily
        WHERE stock_code='{code}' AND date <= '{target_date}'
        ORDER BY date DESC LIMIT 200
    """).fetchall()
    if len(rows) < 120:
        return None

    # 特征计算（与scoring.py完全一致）
    base_raw, dt_str = compute_raw_features(code, rows, conn)
    if base_raw is None:
        return None

    feat = standardize_v5(base_raw.copy())

    # GTJA
    gtja_v = gtja_data(code, target_date) if gtja_names_list else []
    gtja_arr = np.array(gtja_v[:11], dtype=np.float64)
    if len(gtja_arr) < 11:
        gtja_arr = np.pad(gtja_arr, (0, 11 - len(gtja_arr)), 'constant')

    feat_full = np.append(feat, gtja_arr)
    if len(feat_full) < 37:
        feat_full = np.pad(feat_full, (0, 37 - len(feat_full)), 'constant')
    else:
        feat_full = feat_full[:37]
    feat_full = np.nan_to_num(feat_full, nan=0.0)

    # 标准化
    feat_s = apply_norm(feat_full, norm_stats).reshape(1, -1)

    pred = float(model.predict(feat_s)[0])
    return pred


def main():
    t0 = time.time()
    print("=" * 65)
    print("📊 20d 模型回测 — 新特征管线")
    print(f"  策略: 每月首日选Top{TOP_N} 等权重 持有{FWD_DAYS}日")
    print(f"  期间: {TEST_START} ~ 至今")
    print(f"  本金: {INITIAL_CAP:,.0f}")
    print("=" * 65)

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    # 加载模型
    print("\n📡 加载模型...")
    model, norm_stats = load_model()
    print(f"  {model.num_trees()}棵树, {model.num_feature()}维")

    # 加载GTJA紧凑格式（直接dict查找，不用get_gtja_signals）
    gtja_compact = None
    gtja_names = []
    compact_path = MODEL_DIR / 'gtja_compact.pkl'
    if compact_path.exists():
        import pickle
        with open(compact_path, 'rb') as f:
            gtja_compact = pickle.load(f)
        gtja_names = sorted(gtja_compact.keys())[:11]
        print(f"  GTJA: {len(gtja_names)}个因子 (紧凑)")

    def get_gtja(code, date):
        """从紧凑格式查GTJA"""
        if gtja_compact is None:
            return []
        vals = []
        for gn in gtja_names:
            cm = gtja_compact.get(gn, {})
            cm2 = cm.get(code, {})
            v = cm2.get(date, 0.0)
            if v == 0.0 and cm2:
                from datetime import datetime, timedelta
                for off in range(1, 16):
                    pd = (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=off)).strftime('%Y-%m-%d')
                    if pd in cm2:
                        v = cm2[pd]
                        break
            vals.append(v)
        return vals

    # 预加载指数缓存
    print("📡 预加载指数缓存...")
    _load_index_cache(conn)

    # 获取所有股票的列表（排除ST/北交所）
    stocks = [r[0] for r in conn.execute("""
        SELECT stock_code FROM stock_info
        WHERE stock_code NOT LIKE '8%' AND stock_code NOT LIKE '4%'
          AND board != '北交所' AND (stock_name NOT LIKE '%ST%' OR stock_name IS NULL)
    """).fetchall()]
    print(f"  股票池: {len(stocks)} 只")

    # 获取回测期间的每月首日
    trade_dates = [str(r[0])[:10] for r in conn.execute(f"""
        SELECT DISTINCT date FROM stock_daily
        WHERE date >= '{TEST_START}' ORDER BY date
    """).fetchall()]

    # 每月首日
    months = {}
    for d in trade_dates:
        m = d[:7]
        if m not in months:
            months[m] = d
    rebalance_dates = sorted(months.values())
    print(f"  调仓日: {len(rebalance_dates)} 个 ({rebalance_dates[0]} ~ {rebalance_dates[-1]})")

    # 模拟交易
    cash = INITIAL_CAP
    positions = {}  # code -> {shares, avg_cost, buy_date}
    nav_history = []
    daily_values = []

    for ri, rebal_date in enumerate(rebalance_dates):
        preds = []
        # 全市场预测
        for si, code in enumerate(stocks):
            p = predict_one(code, rebal_date, conn, model, norm_stats, get_gtja, gtja_names)
            if p is not None:
                preds.append((code, p))
            if (si + 1) % 1000 == 0:
                print(f"  预测: [{si+1}/{len(stocks)}] {time.time()-t0:.0f}s", flush=True)

        if not preds:
            continue

        # 排序取TOP_N
        preds.sort(key=lambda x: x[1], reverse=True)
        top_codes = [p[0] for p in preds[:TOP_N]]

        # 获取实时价格
        top_prices = {}
        for code in top_codes:
            r = conn.execute(f"""
                SELECT close FROM stock_daily
                WHERE stock_code='{code}' AND date<='{rebal_date}'
                ORDER BY date DESC LIMIT 1
            """).fetchone()
            if r:
                top_prices[code] = float(r[0])

        # 卖出旧持仓（非新选中）
        for code in list(positions.keys()):
            if code not in top_codes:
                pos = positions[code]
                price = top_prices.get(code) or conn.execute(f"""
                    SELECT close FROM stock_daily WHERE stock_code='{code}'
                    AND date<='{rebal_date}' ORDER BY date DESC LIMIT 1
                """).fetchone()
                if price:
                    price = float(price[0]) if isinstance(price, tuple) else price
                    sell_price = price * (1 - SLIPPAGE)
                    revenue = pos['shares'] * sell_price * (1 - COMMISSION)
                    pnl = revenue - pos['shares'] * pos['avg_cost']
                    cash += revenue
                    del positions[code]

        # 买入新持仓
        if top_prices:
            per_stock = cash / max(len(top_codes), 1)
            for code in top_codes:
                price = top_prices.get(code)
                if not price or price <= 0:
                    continue
                buy_price = price * (1 + SLIPPAGE)
                shares = int(per_stock / buy_price / 100) * 100
                if shares < 100:
                    continue
                cost = shares * buy_price * (1 + COMMISSION)
                if cost > cash:
                    shares = int(cash * 0.95 / buy_price / 100) * 100
                    if shares < 100:
                        continue
                    cost = shares * buy_price * (1 + COMMISSION)
                positions[code] = {'shares': shares, 'avg_cost': cost / shares, 'buy_date': rebal_date}
                cash -= cost

        # 记录NAV
        pos_val = 0
        for code, pos in positions.items():
            r = conn.execute(f"""
                SELECT close FROM stock_daily WHERE stock_code='{code}'
                AND date<='{rebal_date}' ORDER BY date DESC LIMIT 1
            """).fetchone()
            price = float(r[0]) if r else 0
            pos_val += pos['shares'] * price

        nav = cash + pos_val
        nav_history.append({'date': rebal_date, 'nav': round(nav, 2), 'cash': round(cash, 2),
                           'pos_count': len(positions)})

        print(f"  [{ri+1}/{len(rebalance_dates)}] {rebal_date}  "
              f"NAV={nav:,.0f}  持仓={len(positions)}  现金={cash:,.0f}",
              flush=True)

    conn.close()

    # ── 绩效评估 ──
    print("\n" + "=" * 65)
    print("📊 回测结果")
    print("=" * 65)

    final_nav = nav_history[-1]['nav']
    total_ret = (final_nav / INITIAL_CAP - 1) * 100
    n_months = len(nav_history)
    years = n_months / 12

    # 月收益率
    monthly_rets = []
    for i in range(1, len(nav_history)):
        r = (nav_history[i]['nav'] / nav_history[i-1]['nav'] - 1) * 100
        monthly_rets.append(r)
    monthly_rets = np.array(monthly_rets)

    avg_ret = np.mean(monthly_rets)
    std_ret = np.std(monthly_rets, ddof=1)
    annual_ret = ((final_nav / INITIAL_CAP) ** (1 / years) - 1) * 100 if years > 0 else 0
    annual_vol = std_ret * math.sqrt(12)
    sharpe = (avg_ret / std_ret) * math.sqrt(12) if std_ret > 0 else 0

    # 最大回撤
    nvs = np.array([h['nav'] for h in nav_history])
    peak = np.maximum.accumulate(nvs)
    dd = (nvs - peak) / peak * 100
    max_dd = np.min(dd)
    max_dd_idx = np.argmin(dd)

    # 胜率
    win_rate = np.sum(monthly_rets > 0) / len(monthly_rets) * 100 if len(monthly_rets) > 0 else 0

    print(f"\n{'指标':<20} {'值':>12}")
    print(f"{'─'*32}")
    print(f"{'总收益率':<20} {total_ret:>+10.2f}%")
    print(f"{'年化收益率':<20} {annual_ret:>+10.2f}%")
    print(f"{'年化波动率':<20} {annual_vol:>10.2f}%")
    print(f"{'夏普比率':<20} {sharpe:>10.2f}")
    print(f"{'最大回撤':<20} {max_dd:>10.2f}%")
    print(f"{'月胜率':<20} {win_rate:>9.1f}%")
    print(f"{'调仓次数':<20} {n_months:>10d}")
    print(f"{'最终NAV':<20} {final_nav:>10,.0f}")

    # NAV曲线
    print(f"\n📈 NAV曲线:")
    for h in nav_history[::max(1, len(nav_history)//10)]:
        print(f"  {h['date']}  NAV={h['nav']:>8,.0f}  持仓{h['pos_count']}")

    # 逐年
    print(f"\n📅 逐年:")
    yearly = {}
    for h in nav_history:
        y = h['date'][:4]
        if y not in yearly:
            yearly[y] = []
        yearly[y].append(h)
    for y, hlist in sorted(yearly.items()):
        if len(hlist) < 2:
            continue
        first = hlist[0]['nav']
        last = hlist[-1]['nav']
        ret = (last / first - 1) * 100
        print(f"  {y}: {ret:+.2f}%  ({first:,.0f} → {last:,.0f})")

    # 保存结果
    res = {
        'total_return': round(total_ret, 2),
        'annual_return': round(annual_ret, 2),
        'annual_vol': round(annual_vol, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_dd, 2),
        'win_rate': round(win_rate, 1),
        'trades': n_months,
        'final_nav': round(final_nav, 2),
        'nav_history': nav_history,
        'time_sec': round(time.time() - t0),
    }
    with open(MODEL_DIR / 'bt_20d_results.json', 'w') as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(f"\n💾 结果已保存: {MODEL_DIR / 'bt_20d_results.json'}")
    print(f"⏱ {time.time()-t0:.0f}s")


if __name__ == '__main__':
    main()
