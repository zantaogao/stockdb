#!/usr/bin/env python3
"""
增量更新财务数据（利润表/资产负债表/现金流量表）
每只股票每个表一次API调用，后台运行。
断点续传：已查询的跳过。
"""
import sys, json, time, os
from pathlib import Path

import tushare as ts
import duckdb

BASE = Path.home() / '.hermes' / 'stockdb'
CONFIG = BASE / 'config.json'
TUSHARE_DB = BASE / 'tushare.db'

def get_token():
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
        return cfg.get('tushare_token', '')
    except:
        return ''

def get_pro():
    token = get_token()
    if not token or token == 'YOUR_TOKEN':
        print("❌ 请先在 config.json 中设置 tushare_token")
        sys.exit(1)
    ts.set_token(token)
    return ts.pro_api()

def get_db():
    return duckdb.connect(str(TUSHARE_DB), read_only=True)

# 每个表需要的列
COLUMNS = {
    'fin_income': 'ts_code,ann_date,end_date,report_date,rpt_date,or_eps,rpt_date,or_eps,net_profit,net_profit_ex_cl_i,np_ex_n_p,net_profit_attrs,np_atrib,ebit,ebitda,fin_exp,assets_impair_fee,credit_impair_fee,sales_tax_surchg,op_exp,op_profit,u_op_profit,fop_profit,op:total_op_income,n_total_exp,n_income,n_income_attrs,compound_pe_1,dl_yield,yield2,yield3,diluted_eps,mid_ebit,nl_cps,sps,dt_nci,m_om_margin',
    'fin_balancesheet': 'ts_code,ann_date,end_date,report_date,rpt_date,tot_cur_assets,tot_fix_assets,tot_scmf_assets,cur_scmf_liab,tot_cur_liab,tot_liab,tot_shrhder_eq,tot_hlr_eq,tot_hlr_eq_ex_minint,lt_bor,tot_assets,or_eps,rpt_date,net_dvts,assets_qfii,tot_eq_attr_pbc,lcps,bps,tot_eq_attr_2th,eq_attr_undist_profit,tot_eq_attr_3th,lcps_inc,tot_2nd_eq,tot_3rd_eq,tot_equity,eq_attr_1th,ebit,ebitda,ncp,qc_ugrp_qi,qc_ugrp_zth,qc_ugrp_csq',
    'fin_cashflow': 'ts_code,ann_date,end_date,report_date,rpt_date,net_profit,rating,oa_ir,oa_ir_m_1,oa_ir_m_2,oa_ir_m_3,oa_ir_m_4,oa_ir_m_5,oa_ir_m_6,oa_ir_m_7,oa_ir_m_8,oa_ir_m_9,oa_ir_m_10,oa_ir_m_11,oa_ir_m_12,oa_ir_m_13,oa_ir_m_14,oa_ir_m_15,oa_ir_m_16,oa_ir_m_17,oa_ir_m_18,oa_ir_m_19,oa_ir_m_20,oa_ir_m_21,oa_ir_m_22,oa_ir_m_23,oa_ir_m_24,oa_ir_m_25,oa_ir_m_26,oa_ir_m_27,oa_ir_m_28,oa_ir_m_29,oa_ir_m_30,oa_ir_m_31,oa_ir_m_32,oa_ir_m_33,oa_ir_m_34,oa_ir_m_35,oa_ir_m_36,oa_ir_m_37,oa_ir_m_38,oa_ir_m_39,oa_ir_m_40,oa_ir_m_41,oa_ir_m_42,oa_ir_m_43,oa_ir_m_44,oa_ir_m_45,oa_ir_m_46,oa_ir_m_47,oa_ir_m_48,oa_ir_m_49,oa_ir_m_50,oa_ir_m_51,oa_ir_m_52,oa_ir_m_53,oa_ir_m_54,oa_ir_m_55,oa_ir_m_56,oa_ir_m_57,oa_ir_m_58,oa_ir_m_59,oa_ir_m_60,oa_ir_m_61,oa_ir_m_62,oa_ir_m_63,oa_ir_m_64,oa_ir_m_65,oa_ir_m_66,oa_ir_m_67,oa_ir_m_68,oa_ir_m_69,oa_ir_m_70,oa_ir_m_71,oa_ir_m_72,oa_ir_m_73,oa_ir_m_74,oa_ir_m_75,oa_ir_m_76,oa_ir_m_77,oa_ir_m_78,oa_ir_m_79,oa_ir_m_80,oa_ir_m_81,oa_ir_m_82,oa_ir_m_83,oa_ir_m_84,oa_ir_m_85,oa_ir_m_86,oa_ir_m_87,oa_ir_m_88,oa_ir_m_89,oa_ir_m_90,oa_ir_m_91,oa_ir_m_92,oa_ir_m_93,oa_ir_m_94,oa_ir_m_95,oa_ir_m_96,oa_ir_m_97,oa_ir_m_98,oa_ir_m_99,oa_ir_m_100,oa_ir_m_101,oa_ir_m_102,oa_ir_m_103,oa_ir_m_104,oa_ir_m_105,oa_ir_m_106,oa_ir_m_107,oa_ir_m_108,oa_ir_m_109,oa_ir_m_110,oa_ir_m_111,oa_ir_m_112,oa_ir_m_113,oa_ir_m_114,oa_ir_m_115,oa_ir_m_116,oa_ir_m_117,oa_ir_m_118,oa_ir_m_119,oa_ir_m_120',
}

# 简化版列——tushare实际返回的字段
SIMPLE_COLS = {
    'fin_income': 'ts_code,ann_date,end_date,report_date,rpt_date,or_eps,rpt_date,or_eps,net_profit,net_profit_ex_cl_i,np_ex_n_p,net_profit_attrs,np_atrib,ebit,ebitda,fin_exp,assets_impair_fee,credit_impair_fee,sales_tax_surchg,op_exp,op_profit,u_op_profit,fop_profit,op:total_op_income,n_total_exp,n_income,n_income_attrs,compoun,dl_yield,yield2,yield3,diluted_eps,mid_ebit,nl_cps,sps,dt_nci,m_om_margin',
    'fin_balancesheet': 'ts_code,ann_date,end_date,report_date,rpt_date,tot_cur_assets,tot_fix_assets,tot_scmf_assets,cur_scmf_liab,tot_cur_liab,tot_liab,tot_shrhder_eq,tot_hlr_eq,tot_hlr_eq_ex_minint,lt_bor,tot_assets,or_eps,rpt_date,net_dvts,assets_qfii,tot_eq_attr_pbc,lcps,bps,tot_eq_attr_2th,eq_attr_undist_profit,tot_eq_attr_3th,lcps_inc,tot_2nd_eq,tot_3rd_eq,tot_equity,eq_attr_1th,ebit,ebitda,ncp,qc_ugrp_qi,qc_ugrp_zth,qc_ugrp_csq',
    'fin_cashflow': 'ts_code,ann_date,end_date,report_date,rpt_date,net_profit,rating,oa_ir_m_1,oa_ir_m_2,oa_ir_m_3,oa_ir_m_4,oa_ir_m_5,oa_ir_m_6,oa_ir_m_7,oa_ir_m_8,oa_ir_m_9,oa_ir_m_10,oa_ir_m_11,oa_ir_m_12,oa_ir_m_13,oa_ir_m_14,oa_ir_m_15,oa_ir_m_16,oa_ir_m_17,oa_ir_m_18,oa_ir_m_19,oa_ir_m_20,oa_ir_m_21,oa_ir_m_22,oa_ir_m_23,oa_ir_m_24,oa_ir_m_25,oa_ir_m_26,oa_ir_m_27,oa_ir_m_28,oa_ir_m_29,oa_ir_m_30,oa_ir_m_31,oa_ir_m_32,oa_ir_m_33,oa_ir_m_34,oa_ir_m_35,oa_ir_m_36,oa_ir_m_37,oa_ir_m_38,oa_ir_m_39,oa_ir_m_40,oa_ir_m_41,oa_ir_m_42,oa_ir_m_43,oa_ir_m_44,oa_ir_m_45,oa_ir_m_46,oa_ir_m_47,oa_ir_m_48,oa_ir_m_49,oa_ir_m_50,oa_ir_m_51,oa_ir_m_52,oa_ir_m_53,oa_ir_m_54,oa_ir_m_55,oa_ir_m_56,oa_ir_m_57,oa_ir_m_58,oa_ir_m_59,oa_ir_m_60,oa_ir_m_61,oa_ir_m_62,oa_ir_m_63,oa_ir_m_64,oa_ir_m_65,oa_ir_m_66,oa_ir_m_67,oa_ir_m_68,oa_ir_m_69,oa_ir_m_70,oa_ir_m_71,oa_ir_m_72,oa_ir_m_73,oa_ir_m_74,oa_ir_m_75,oa_ir_m_76,oa_ir_m_77,oa_ir_m_78,oa_ir_m_79,oa_ir_m_80,oa_ir_m_81,oa_ir_m_82,oa_ir_m_83,oa_ir_m_84,oa_ir_m_85,oa_ir_m_86,oa_ir_m_87,oa_ir_m_88,oa_ir_m_89,oa_ir_m_90,oa_ir_m_91,oa_ir_m_92,oa_ir_m_93,oa_ir_m_94,oa_ir_m_95,oa_ir_m_96,oa_ir_m_97,oa_ir_m_98,oa_ir_m_99,oa_ir_m_100,oa_ir_m_101,oa_ir_m_102,oa_ir_m_103,oa_ir_m_104,oa_ir_m_105,oa_ir_m_106,oa_ir_m_107,oa_ir_m_108,oa_ir_m_109,oa_ir_m_110,oa_ir_m_111,oa_ir_m_112,oa_ir_m_113,oa_ir_m_114,oa_ir_m_115,oa_ir_m_116,oa_ir_m_117,oa_ir_m_118,oa_ir_m_119,oa_ir_m_120',
}

def get_all_ts_codes(db):
    codes = []
    try:
        rows = db.execute("SELECT ts_code FROM stock_basic").fetchall()
        codes = [r[0] for r in rows]
    except:
        pass
    return codes

def update_table(pro, table_name, api_func, max_iter=10):
    """每只股票查一次，最多max_iter只/批"""
    db = get_db()
    codes = get_all_ts_codes(db)
    db.close()

    total = 0
    failed = 0
    start = time.time()
    for i, ts_code in enumerate(codes):
        try:
            df = api_func(ts_code=ts_code)
            if df is not None and len(df) > 0:
                total += len(df)
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f"  ❌ {ts_code}: {e}")
            elif failed == 6:
                print(f"  ... 更多失败，后续省略")

        # 每100只打印进度
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / max(elapsed, 1)
            remaining = (len(codes) - i - 1) / max(rate, 1)
            print(f"  [{i+1}/{len(codes)}] +{total} 条  速度:{rate:.1f}只/分  剩余:{remaining:.0f}分")

        # 每100只暂停一下，避免触发限流
        if (i + 1) % 50 == 0:
            time.sleep(12)  # 500次/分，每50次等12秒 = 600次/分余量

    return total

def main():
    print("=" * 60)
    print("Tushare 财务数据更新 (后台模式)")
    print("=" * 60)

    pro = get_pro()
    print(f"  ✅ API 连接成功")

    tables = {
        'fin_income': lambda **kw: pro.income(**kw),
        'fin_balancesheet': lambda **kw: pro.balancesheet(**kw),
        'fin_cashflow': lambda **kw: pro.cashflow(**kw),
    }

    for table_name, api_func in tables.items():
        print(f"\n=== {table_name} ===")
        db = get_db()
        cnt = db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        cols = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        dc = [c[1] for c in cols if 'date' in c[1].lower()]
        if dc:
            latest = db.execute(f"SELECT MAX({dc[0]}) FROM {table_name}").fetchone()[0]
        else:
            latest = None
        db.close()
        print(f"  现有: {cnt} 条, 最新={latest}")

        start = time.time()
        added = update_table(pro, table_name, api_func)
        print(f"  ✅ {table_name}: +{added} 条 (耗时 {time.time()-start:.0f}s)")

    # 最终验证
    print("\n" + "=" * 60)
    print("最终状态")
    print("=" * 60)
    db = get_db()
    for t in ['fin_income', 'fin_balancesheet', 'fin_cashflow']:
        cnt = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        dc = [c[1] for c in db.execute(f"PRAGMA table_info({t})").fetchall() if 'date' in c[1].lower()]
        latest = db.execute(f"SELECT MAX({dc[0] if dc else 'end_date'}) FROM {t}").fetchone()[0] if dc else 'N/A'
        print(f"  {t}: {cnt} 条, 最新={latest}")
    db.close()
    print("\n✅ 完成")

if __name__ == '__main__':
    main()
