"""
数据完整性校验 v1
===================
检查所有账户状态文件、信号缓存、模型文件、数据库完整性。
"""
import os, json
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
SIGNALS_DIR = BASE / 'signals'
MODELS_DIR = BASE / 'models'
ACCOUNTS_DIR = BASE / 'sim_accounts'

def check_all():
    results = {}

    # 1. 账户文件
    accts = {}
    for aid in ['main', 'short', 'sim']:
        f = ACCOUNTS_DIR / f'{aid}.json'
        if not f.exists():
            accts[aid] = {'ok': False, 'message': f'{f} 不存在'}
        else:
            try:
                with open(f) as fh:
                    data = json.load(fh)
                # 检查必需字段
                for field in ['id', 'name', 'cash', 'positions', 'trades', 'nav_history']:
                    if field not in data:
                        accts[aid] = {'ok': False, 'message': f'缺少字段: {field}'}
                        break
                else:
                    accts[aid] = {'ok': True, 'message': f'有效 (资金: {data["cash"]:.2f})'}
            except Exception as e:
                accts[aid] = {'ok': False, 'message': f'JSON解析错误: {e}'}
    results['账户状态'] = accts

    # 2. 信号缓存
    signal_ok = True
    msg = ''
    if not SIGNALS_DIR.exists():
        signal_ok = False
        msg = 'signals/ 目录不存在'
    else:
        json_files = [f for f in SIGNALS_DIR.glob('*.json')]
        if not json_files:
            signal_ok = False
            msg = '无缓存信号文件'
        else:
            for f in json_files[-1:]:  # 检查最新一个
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                    if 'scores' not in data:
                        signal_ok = False
                        msg = f'{f.name} 缺少 scores 字段'
                        break
                except Exception as e:
                    signal_ok = False
                    msg = f'{f.name} 解析错误: {e}'
                    break
            else:
                msg = f'OK ({len(json_files)} 天缓存)'
    results['信号缓存'] = {'ok': signal_ok, 'message': msg}

    # 3. 模型文件
    model_ok = True
    model_msg = ''
    for mf in ['lgb_reg_model.txt', '10d', '40d']:
        p = MODELS_DIR / mf
        if not p.exists():
            model_ok = False
            model_msg += f'缺少 {mf}; '
    for sf in ['v6_norm_stats.json', 'v10_norm_stats.json']:
        p = MODELS_DIR / sf
        if not p.exists():
            model_ok = False
            model_msg += f'缺少 {sf}; '
    if not model_msg:
        model_msg = '所有模型文件存在'
    results['模型文件'] = {'ok': model_ok, 'message': model_msg}

    # 4. 配置
    config_path = BASE / 'config.json'
    if config_path.exists():
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            if 'tushare_token' in cfg:
                tok = cfg['tushare_token']
                if tok == 'YOUR_TOKEN' or len(tok) < 8:
                    results['配置'] = {'ok': False, 'message': 'tushare_token 未设置'}
                else:
                    results['配置'] = {'ok': True, 'message': 'tushare_token 已设置'}
            else:
                results['配置'] = {'ok': True, 'message': '配置正常'}
        except Exception as e:
            results['配置'] = {'ok': False, 'message': f'解析错误: {e}'}
    else:
        results['配置'] = {'ok': False, 'name': 'config.json'}
        results['配置']['message'] = 'config.json 不存在'

    # 5. 数据库
    try:
        import sqlite3
        db_path = BASE / 'stock_prices.db'
        if not db_path.exists():
            results['数据库'] = {'ok': False, 'message': 'stock_prices.db 不存在'}
        else:
            try:
                conn = sqlite3.connect(str(db_path))
                tables = [t[0] for t in conn.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()]
                if not tables:
                    results['数据库'] = {'ok': False, 'message': '数据库中没有表'}
                else:
                    total_rows = sum(conn.execute(f'SELECT COUNT(*) FROM [{t}]').fetchone()[0] for t in tables if 'daily' in t or 'minute' in t)
                    results['数据库'] = {'ok': True, 'message': f'OK ({len(tables)} tables, {total_rows} daily/minute rows)'}
                    conn.close()
            except Exception as e:
                results['数据库'] = {'ok': False, 'message': f'数据库错误: {e}'}
    except ImportError:
        results['数据库'] = {'ok': False, 'message': 'sqlite3 模块不可用'}

    return results


if __name__ == '__main__':
    results = check_all()
    for k, v in results.items():
        status = '✅' if v['ok'] else '❌'
        print(f'  {status} {k}: {v["message"]}')
