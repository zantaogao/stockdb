"""Fix _handle_analyze in server_dashboard.py"""
import re, textwrap

with open('/Users/zantao/.hermes/stockdb/server_dashboard.py', 'r') as f:
    lines = f.readlines()

# Find _handle_analyze function boundaries
start = None
end = None
for i, line in enumerate(lines):
    if 'def _handle_analyze(self, code):' in line:
        start = i
    if 'def _handle_etf_analyze' in line and start and i > start:
        end = i
        break
if end is None:
    for i, line in enumerate(lines):
        if 'def log_message' in line and start and i > start:
            end = i
            break

print(f'_handle_analyze: lines {start} to {end} (0-indexed)')
if start is None or end is None:
    print('Could not find boundaries!')
    exit(1)

# Build replacement function body
func_code = '''\
    def _handle_analyze(self, code):
        """个股诊断：从 tushare.db 读取完整数据，实时计算技术面+模型评分"""
        if '.' not in code:
            code = f"{code}.SH" if code.startswith('6') else f"{code}.SZ"
        code_short = code.replace('.SH', '').replace('.SZ', '')
        from core.db import get_tushare_db
        import time
        conn = None
        for attempt in range(5):
            try:
                conn = get_tushare_db()
                break
            except Exception:
                if attempt < 4:
                    time.sleep(2)
                else:
                    self._json({"error": "数据库被更新进程占用，请稍后再试"})
                    return
        basic = conn.execute("SELECT name, industry FROM stock_basic WHERE ts_code=?", [code]).fetchone()
        if not basic:
            conn.close()
            self._json({"error": f"未找到股票 {code}"})
            return
        name, industry = basic
        rows = conn.execute(f"""\
            SELECT trade_date, close, open, high, low, pct_chg, vol, amount
            FROM daily WHERE ts_code='{code}'
            ORDER BY trade_date DESC LIMIT 120
        """).fetchall()
        if len(rows) < 5:
            conn.close()
            self._json({"error": f"日线数据不足 (仅{len(rows)}天)"})
            return
        closes = [float(r[1]) for r in rows]
        vols = [float(r[6]) for r in rows]
        pcts = [float(r[5]) for r in rows]
        dates = [str(r[0]) for r in rows]
        latest_date = dates[0]
        latest_price = closes[0]
        prev_close = closes[1] if len(closes) > 1 else latest_price
        change_pct = round((latest_price / prev_close - 1) * 100, 2)
        ma5 = sum(closes[:5])/5 if len(closes)>=5 else None
        ma10 = sum(closes[:10])/10 if len(closes)>=10 else None
        ma20 = sum(closes[:20])/20 if len(closes)>=20 else None
        ma60 = sum(closes[:60])/60 if len(closes)>=60 else None
        ma120 = sum(closes[:120])/120 if len(closes)>=120 else None
        avg_vol5 = sum(vols[1:6])/5 if len(vols)>=6 else None
        vol_ratio = round(vols[0]/avg_vol5, 2) if avg_vol5 and avg_vol5>0 else None
        dev120 = round((latest_price-ma120)/ma120*100,2) if ma120 else None
        chg60 = round((closes[0]/closes[min(59,len(closes)-1)]-1)*100,2) if len(closes)>=60 else None
        mf_rows = conn.execute(f"""\
            SELECT date, main_net FROM money_flow
            WHERE stock_code='{code_short}'
            ORDER BY date DESC LIMIT 5
        """).fetchall()
        mf_5d = []
        mf_total = 0
        for mf in mf_rows:
            val = float(mf[1])/10000 if mf[1] else 0
            mf_5d.append({"date": str(mf[0])[:10], "net": round(val,2)})
            mf_total += val
        money_flow = round(mf_5d[0]["net"],2) if mf_5d else None
        if money_flow is not None and abs(money_flow)<0.01:
            raw_val = float(mf_rows[0][1]) if mf_rows and mf_rows[0][1] else 0
            money_flow_display = f"{raw_val:+.0f}万"
        elif money_flow is not None:
            money_flow_display = f"{money_flow:+.2f}亿"
        else:
            money_flow_display = None
        if mf_5d and abs(mf_total)<0.01:
            raw_total = sum(float(m[1] or 0) for m in mf_rows)
            money_flow_5d = f"{raw_total:+.0f}万"
        elif mf_5d:
            money_flow_5d = f"{mf_total:+.2f}亿"
        else:
            money_flow_5d = None
        fusion_score = None
        reg10 = reg20 = reg40 = None
        try:
            from core.scoring import score_stock
            sr = score_stock(code_short)
            if sr:
                fusion_score = round(sr.get("fusion",0),1)
                reg10 = round(sr.get("reg10_pred",0),2)
                reg20 = round(sr.get("reg20_pred",0),1)
                reg40 = round(sr.get("reg40_pred",0),1)
        except:
            pass
        conn.close()
        rp = []
        rp.append(f"\\U0001f4ca {name} ({code_short}) \\u8bca\\u65ad\\u62a5\\u544a")
        rp.append(f"\\u884c\\u4e1a\\uff1a{industry} | \\u65e5\\u671f\\uff1a{latest_date}")
        rp.append(f"\\u73b0\\u4ef7\\uff1a{latest_price:.2f} | \\u6da8\\u8dcc\\uff1a{change_pct:+.2f}% | \\u91cf\\u6bd4\\uff1a{vol_ratio if vol_ratio else '-'}")
        if chg60: rp.append(f"60 \\u65e5\\u6da8\\u8dcc\\uff1a{chg60:+.1f}%")
        ma_parts = []
        if ma5: ma_parts.append(f"MA5={ma5:.2f}{chr(8593) if latest_price>ma5 else chr(8595)}")
        if ma10: ma_parts.append(f"MA10={ma10:.2f}{chr(8593) if latest_price>ma10 else chr(8595)}")
        if ma20: ma_parts.append(f"MA20={ma20:.2f}{chr(8593) if latest_price>ma20 else chr(8595)}")
        if ma60: ma_parts.append(f"MA60={ma60:.2f}{chr(8593) if latest_price>ma60 else chr(8595)}")
        if ma120: ma_parts.append(f"MA120={ma120:.2f}{chr(8593) if latest_price>ma120 else chr(8595)}")
        rp.append(f"\\u5747\\u7ebf\\uff1a{' | '.join(ma_parts)}")
        if ma5 and ma20 and ma60:
            if ma5>ma20>ma60: rp.append("\\u2705 \\u591a\\u5934\\u6392\\u5217 (5>20>60)")
            elif ma5<ma20<ma60: rp.append("\\u26a0\\ufe0f \\u7a7a\\u5934\\u6392\\u5217 (5<20<60)")
            elif ma5>ma20: rp.append("\\u25fb \\u77ed\\u671f\\u504f\\u591a (5>20)")
            else: rp.append("\\u25fb \\u77ed\\u671f\\u504f\\u7a7a (5<20)")
        if dev120 is not None:
            if abs(dev120)<3: rp.append(f"\\u8d34\\u8fd1\\u5e74\\u7ebf ({dev120:+.1f}%)")
            elif dev120>0: rp.append(f"\\u5e74\\u7ebf\\u4e0a\\u65b9 {dev120:.1f}%")
            else: rp.append(f"\\u5e74\\u7ebf\\u4e0b\\u65b9 {abs(dev120):.1f}%")
        if vol_ratio:
            if vol_ratio>2 and change_pct>3: rp.append(f"\\U0001f4c8 \\u653e\\u91cf\\u4e0a\\u653b (x{vol_ratio:.1f})")
            elif vol_ratio>2 and change_pct<-3: rp.append(f"\\U0001f4c9 \\u653e\\u91cf\\u4e0b\\u8dcc (x{vol_ratio:.1f})")
            elif vol_ratio<0.5: rp.append(f"\\u7f29\\u91cf\\u6574\\u7406 (x{vol_ratio:.1f})")
            else: rp.append(f"\\u91cf\\u80fd\\u6b63\\u5e38 (x{vol_ratio:.1f})")
        if len(closes)>=20:
            lo=min(closes[:20]); hi=max(closes[:20])
            pp=(latest_price-lo)/(hi-lo)*100
            rp.append(f"20\\u65e5\\u533a\\u95f4\\uff1a{lo:.2f}~{hi:.2f}\\uff0c\\u5f53\\u524d\\u4f4d\\u4e8e{pp:.0f}%\\u5206\\u4f4d")
        if len(pcts)>=5:
            up5=sum(1 for p in pcts[:5] if p>0); dn5=sum(1 for p in pcts[:5] if p<0)
            if up5>=4: rp.append("\\U0001f4c8 \\u8fd15\\u65e5\\u5f3a\\u52bf\\uff084\\u9633+\\uff09")
            elif dn5>=4: rp.append("\\U0001f4c9 \\u8fd15\\u65e5\\u5f31\\u52bf\\uff084\\u9634+\\uff09")
            elif up5>=3: rp.append("\\u25fb \\u8fd15\\u65e5\\u504f\\u591a")
            elif dn5>=3: rp.append("\\u25fb \\u8fd15\\u65e5\\u504f\\u7a7a")
        if money_flow is not None:
            rp.append(f"\\u4e3b\\u529b\\u8d44\\u91d1\\uff1a{money_flow_display}\\uff085\\u65e5\\u7d2f\\u8ba1\\uff1a{money_flow_5d}\\uff09")
        if fusion_score is not None:
            rp.append("---")
            rp.append(f"\\U0001f3af \\u878d\\u5408\\u8bc4\\u5206\\uff1a{fusion_score:.0f}\\u5206")
            rp.append(f"   10d \\u9884\\u6d4b\\uff1a{reg10:+.1f}% | 20d \\u9884\\u6d4b\\uff1a{reg20:+.1f}% | 40d \\u9884\\u6d4b\\uff1a{reg40:+.1f}%")
            if fusion_score>=70: rp.append("\\u2705 \\u5f3a\\u52bf\\u80a1 (\\u524d30%)")
            elif fusion_score>=50: rp.append("\\u25fb \\u4e2d\\u6027\\u80a1")
            else: rp.append("\\u26a0\\ufe0f \\u5f31\\u52bf\\u80a1 (\\u540e50%)")
        vt = []
        tr = sum(1 for t in [latest_price>(ma5 or 0),latest_price>(ma20 or 0),latest_price>(ma60 or 0),latest_price>(ma120 or 0)] if t)
        if tr>=3: vt.append("\\u591a\\u5468\\u671f\\u5171\\u632f\\u504f\\u591a")
        elif tr<=1: vt.append("\\u591a\\u5468\\u671f\\u5171\\u632f\\u504f\\u7a7a")
        if len(closes)>=20:
            if pp>=90: vt.append(f"\\u63a5\\u8fd120\\u65e5\\u7bb1\\u9876({pp:.0f}%)")
            elif pp<=10: vt.append(f"\\u63a5\\u8fd120\\u65e5\\u7bb1\\u5e95({pp:.0f}%)")
        if mf_5d:
            mt=sum(d["net"] for d in mf_5d)
            if mt>0: vt.append(f"5\\u65e5\\u4e3b\\u529b\\u51c0\\u6d41\\u5165{money_flow_5d}")
            elif mt<0: vt.append(f"5\\u65e5\\u4e3b\\u529b\\u51c0\\u6d41\\u51fa{money_flow_5d}")
        pos = sum(1 for t in vt if any(k in t for k in ["\\u504f\\u591a","\\u7a81\\u7834","\\u51c0\\u6d41\\u5165","\\u7bb1\\u5e95"]))
        neg = sum(1 for t in vt if any(k in t for k in ["\\u504f\\u7a7a","\\u4e0b\\u8dcc","\\u51c0\\u6d41\\u51fa","\\u7bb1\\u9876"]))
        if pos>=2 and pos>neg: vd="\\u504f\\u591a"
        elif neg>=2 and neg>pos: vd="\\u504f\\u7a7a"
        else: vd="\\u9707\\u8361"
        for l in vt: rp.append(l)
        rp.append("---")
        rp.append(f"\\u5224\\u65ad\\uff1a{vd} (\\u591a{pos}/\\u7a7a{neg})")
        report = "\\n".join(rp)
        self._json({
            "code": code_short, "name": name, "industry": industry,
            "date": latest_date, "price": latest_price, "change_pct": change_pct,
            "vol_ratio": vol_ratio, "chg60": chg60,
            "ma": {"ma5":ma5,"ma10":ma10,"ma20":ma20,"ma60":ma60,"ma120":ma120},
            "dev120": dev120,
            "money_flow": money_flow, "money_flow_display": money_flow_display,
            "money_flow_5d": money_flow_5d, "money_flow_detail": mf_5d,
            "fusion_score": fusion_score, "reg10": reg10, "reg20": reg20, "reg40": reg40,
            "bullish_count": 0, "verdict": vd,
            "report": report,
        })
'''

# Replace
new_lines = func_code.split('\n')
# Add newline after each line
new_lines = [l + '\n' for l in new_lines]

lines[start:end] = new_lines

with open('/Users/zantao/.hermes/stockdb/server_dashboard.py', 'w') as f:
    f.writelines(lines)
print('Done')
print(f'Replaced lines {start}-{end} with {len(new_lines)} lines')
