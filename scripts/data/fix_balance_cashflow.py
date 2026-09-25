#!/usr/bin/env python3
"""
补缺资产负债表(fin_balance)和现金流表(fin_cashflow)
数据源：同花顺(THS) — stock_financial_debt_ths + stock_financial_cash_ths
"""
import duckdb, os, sys, json, time, random, re
from pathlib import Path
import akshare as ak
import pandas as pd

DB_PATH = Path.home() / '.hermes' / 'stockdb' / 'stock.db'
STATE_FILE = Path.home() / '.hermes' / 'stockdb' / 'fix_financial_state.json'
SLEEP = 0.6

def parse_yi(v):
    """'88.34亿'→88.34, '3418.69万'→0.341869, 空/--→None"""
    if v is None or v == '' or v is False:
        return None
    s = str(v).replace(',', '').strip()
    if s in ('--', '-', '', 'NaN', 'None', 'nan', '0'):
        return None
    try:
        if '亿' in s:
            return float(s.replace('亿', ''))
        elif '万' in s:
            return float(s.replace('万', '')) / 10000
        elif '元' in s:
            return float(s.replace('元', '')) / 1e8
        else:
            return float(s)
    except:
        return None

def get_missing():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    all_codes = [r[0] for r in con.execute("SELECT stock_code FROM stock_info ORDER BY stock_code").fetchall()]
    
    have_bal = set(r[0] for r in con.execute("SELECT DISTINCT stock_code FROM fin_balance").fetchall())
    have_cf = set(r[0] for r in con.execute("SELECT DISTINCT stock_code FROM fin_cashflow").fetchall())
    con.close()
    
    return all_codes, have_bal, have_cf

def process_one(code):
    """拉取资产负债表+现金流并写入"""
    result = {'balance': 0, 'cashflow': 0}
    con = duckdb.connect(str(DB_PATH))
    
    try:
        # ── 资产负债表 ──
        try:
            df = ak.stock_financial_debt_ths(symbol=code)
            if df is not None and not df.empty:
                rows_b = []
                for _, row in df.iterrows():
                    rd = str(row.get('报告期', ''))[:10]
                    if not rd or rd == 'NaT':
                        continue
                    total_assets = parse_yi(row.get('*资产合计'))
                    total_liab = parse_yi(row.get('*负债合计'))
                    net_assets = parse_yi(row.get('*所有者权益（或股东权益）合计'))
                    cash = parse_yi(row.get('货币资金'))
                    if total_assets and total_liab:
                        debt_ratio = round(total_liab / total_assets * 100, 2) if total_assets else None
                    else:
                        debt_ratio = None
                    if total_assets is not None or total_liab is not None:
                        rows_b.append((code, rd, total_assets, total_liab, net_assets, cash, debt_ratio))
                
                if rows_b:
                    con.executemany(
                        """INSERT OR IGNORE INTO fin_balance
                           (stock_code, report_date, total_assets, total_liab, net_assets, cash, debt_ratio)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        rows_b
                    )
                    con.commit()
                    result['balance'] = len(rows_b)
        except Exception as e:
            result['bal_err'] = str(e)[:50]
        
        # ── 现金流表 ──
        try:
            df2 = ak.stock_financial_cash_ths(symbol=code)
            if df2 is not None and not df2.empty:
                rows_cf = []
                for _, row in df2.iterrows():
                    rd = str(row.get('报告期', ''))[:10]
                    if not rd or rd == 'NaT':
                        continue
                    op_cf = parse_yi(row.get('*经营活动产生的现金流量净额'))
                    inv_cf = parse_yi(row.get('*投资活动产生的现金流量净额'))
                    fin_cf = parse_yi(row.get('*筹资活动产生的现金流量净额'))
                    # 自由现金流 = 经营 + 投资
                    free_cf = round(op_cf + inv_cf, 4) if op_cf is not None and inv_cf is not None else None
                    
                    if op_cf is not None:
                        rows_cf.append((code, rd, op_cf, inv_cf, fin_cf, free_cf))
                
                if rows_cf:
                    con.executemany(
                        """INSERT OR IGNORE INTO fin_cashflow
                           (stock_code, report_date, operate_cf, invest_cf, finance_cf, free_cf)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        rows_cf
                    )
                    con.commit()
                    result['cashflow'] = len(rows_cf)
        except Exception as e:
            result['cf_err'] = str(e)[:50]
    
    finally:
        con.close()
    
    return result

def main():
    sys.stdout.reconfigure(line_buffering=True)
    
    force = '--force' in sys.argv
    
    all_codes, have_bal, have_cf = get_missing()
    print(f"全部股票: {len(all_codes)}")
    print(f"已有资产负债表: {len(have_bal)} 只")
    print(f"已有现金流表: {len(have_cf)} 只")
    
    if force:
        todo = all_codes
    else:
        todo = [c for c in all_codes if c not in have_bal or c not in have_cf]
    
    print(f"待处理: {len(todo)} 只")
    if not todo:
        print("全部完成！")
        return
    
    # 从状态文件恢复
    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    done_bal = set(state.get('bal_done', []))
    done_cf = set(state.get('cf_done', []))
    
    todo = [c for c in todo if c not in done_bal or c not in done_cf]
    print(f"排除已完成的: {len(todo)} 只")
    
    start = time.time()
    for i, code in enumerate(todo, 1):
        # 如果资产负债和现金流都已补过，跳过
        if code in done_bal and code in done_cf:
            continue
        
        result = process_one(code)
        b_cnt = result.get('balance', 0)
        cf_cnt = result.get('cashflow', 0)
        err_b = result.get('bal_err', '')
        err_cf = result.get('cf_err', '')
        
        if b_cnt > 0:
            done_bal.add(code)
        if cf_cnt > 0:
            done_cf.add(code)
        
        status = []
        if b_cnt > 0: status.append(f"📋+{b_cnt}")
        elif err_b: status.append(f"📋{err_b}")
        else: status.append(f"📋0")
        if cf_cnt > 0: status.append(f"💧+{cf_cnt}")
        elif err_cf: status.append(f"💧{err_cf}")
        else: status.append(f"💧0")
        
        print(f"  [{i}/{len(todo)}] {code}: {' '.join(status)}", flush=True)
        
        # 每50只保存状态
        if i % 50 == 0:
            state['bal_done'] = list(done_bal)
            state['cf_done'] = list(done_cf)
            STATE_FILE.write_text(json.dumps(state))
            elapsed = time.time() - start
            rate = i / elapsed * 60
            eta = (len(todo) - i) / rate
            print(f"  进度: {i}/{len(todo)}  {rate:.0f}只/分 ETA:{eta:.0f}分", flush=True)
        
        time.sleep(SLEEP + random.uniform(0, 0.2))
    
    state['bal_done'] = list(done_bal)
    state['cf_done'] = list(done_cf)
    STATE_FILE.write_text(json.dumps(state))
    
    elapsed = time.time() - start
    print(f"\n✅ 完成! 耗时{elapsed/60:.1f}分")
    
    con = duckdb.connect(str(DB_PATH), read_only=True)
    c1 = con.execute("SELECT COUNT(DISTINCT stock_code) FROM fin_balance").fetchone()[0]
    c2 = con.execute("SELECT COUNT(DISTINCT stock_code) FROM fin_cashflow").fetchone()[0]
    con.close()
    print(f"资产负债表: {c1}/5522 只")
    print(f"现金流表: {c2}/5522 只")

if __name__ == '__main__':
    main()
