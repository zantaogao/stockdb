import duckdb
boards = {
 "三模型融合": [("001332","锡装股份",9.8),("688191","智洋创新",9.4),("688081","兴图新科",9.0),("688377","迪威尔",8.8),("603966","法兰泰克",8.5),("600076","康欣新材",7.9),("688155","先惠技术",7.9),("688399","硕世生物",7.8),("300274","阳光电源",7.7),("002674","兴业科技",7.6)],
 "CMMR独立": [("603102","百合股份",100.0),("603036","如通股份",100.0),("000931","中关村",100.0),("300935","盈建科",100.0),("688265","南模生物",100.0),("600594","益佰制药",100.0),("300779","惠城环保",100.0),("603758","秦安股份",100.0),("002244","滨江集团",100.0),("300358","楚天科技",100.0)],
 "CMMR+三模型": [("688217","睿昂基因",128.7),("301130","西点药业",128.31),("603102","百合股份",126.75),("301167","建研设计",126.49),("001277","速达股份",126.1),("300886","华业香料",125.45),("688004","博汇科技",125.45),("603089","正裕工业",125.06),("603382","海阳科技",125.06),("688793","倍轻松",124.67)],
 "10d独立": [("300328","宜安科技",None),("600076","康欣新材",None),("002674","兴业科技",None),("000802","北京文化",None),("300357","我武生物",None),("600313","农发种业",None),("002041","登海种业",None),("001260","坤泰股份",None),("300839","博汇股份",None),("001268","联合精密",None)],
 "中枢版Top10": [("002133","广宇集团",None),("603108","润达医疗",None),("600435","北方导航",None),("002066","瑞泰科技",None),("002421","达实智能",None),("688041","海光信息",None),("301199","迈赫股份",None),("605289","罗曼股份",None),("300403","汉宇集团",None),("300165","天瑞仪器",None)],
 "中枢版+三模型": [("001238","浙江正特",99.0),("605598","上海港湾",98.8),("688335","复洁科技",98.7),("688776","国光电气",98.5),("688576","西山科技",98.2),("301005","超捷股份",98.1),("300543","朗科智能",98.0),("688288","鸿泉技术",97.8),("002402","和而泰",97.4),("603040","新坐标",97.4)],
}
codes = sorted({c for b in boards.values() for c,_,_ in b})
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
res = {}
for c in codes:
    for suf in ('.SZ','.SH'):
        ts = c+suf
        rows = con.execute("""SELECT trade_date,close,vol FROM daily WHERE ts_code=? AND trade_date<='20260910'
            ORDER BY trade_date DESC LIMIT 60""", [ts]).fetchall()
        if len(rows) >= 25: break
    if len(rows) < 25:
        res[c] = None; continue
    rows = rows[::-1]
    closes = [r[1] for r in rows]; vols = [r[2] for r in rows]
    close = closes[-1]
    ma20 = sum(closes[-20:])/20
    import statistics
    sd20 = statistics.pstdev(closes[-20:])
    up, lo = ma20+2*sd20, ma20-2*sd20
    bollpos = (close-lo)/(up-lo)*100 if up>lo else 50
    chg5 = (close/closes[-6]-1)*100 if len(closes)>=6 else None
    hi20 = max(closes[-20:]); dist_hi20 = (close/hi20-1)*100
    ma5 = sum(closes[-5:])/5; ma10 = sum(closes[-10:])/10
    v5 = sum(vols[-6:-1])/5 if sum(vols[-6:-1])>0 else 1
    vr = vols[-1]/v5*100
    res[c] = dict(close=round(close,2), dev_ma20=round((close/ma20-1)*100,1), boll=round(bollpos,0),
                  chg5=round(chg5,1), dist_hi20=round(dist_hi20,1), above_ma10=close>ma10,
                  ma10=round(ma10,2), vol_ratio=round(vr,0))
for bname, lst in boards.items():
    print("=====", bname)
    for c,n,s in lst:
        d = res.get(c)
        print(c, n, s, d)
