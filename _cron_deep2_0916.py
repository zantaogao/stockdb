import duckdb, json
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# ---- sectors last 9 trading days, aggregate equal-weight pct_chg by industry ----
print("=== SECTOR traj (equal-avg change_pct by industry, last 9 days) ===")
q = """
WITH d AS (
  SELECT s.date, b.industry, AVG(s.change_pct) avgp
  FROM stock_daily s JOIN stock_info b ON s.stock_code=b.stock_code
  WHERE s.date >= DATE '2026-09-04' AND b.industry IS NOT NULL AND b.industry != ''
  GROUP BY 1,2
), p AS (
  SELECT industry,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-04' THEN avgp END) d0904,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-07' THEN avgp END) d0907,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-08' THEN avgp END) d0908,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-09' THEN avgp END) d0909,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-10' THEN avgp END) d0910,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-11' THEN avgp END) d0911,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-14' THEN avgp END) d0914,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-15' THEN avgp END) d0915,
    MAX(CASE WHEN strftime(date,'%m-%d')='09-16' THEN avgp END) d0916,
    SUM(CASE WHEN strftime(date,'%m-%d')>='09-10' THEN avgp ELSE 0 END) cum5
  FROM d GROUP BY industry
)
SELECT industry,
  ROUND(d0904,1),ROUND(d0907,1),ROUND(d0908,1),ROUND(d0909,1),ROUND(d0910,1),ROUND(d0911,1),ROUND(d0914,1),ROUND(d0915,1),ROUND(d0916,1),ROUND(cum5,2)
FROM p ORDER BY cum5 DESC LIMIT 15
"""
for r in con.execute(q).fetchall(): print(r)
print("--- weakest5 by cum5 ---")
for r in con.execute(q.replace("DESC LIMIT 15","ASC LIMIT 8")).fetchall(): print(r)

# ---- per-stock daily pattern table ----
codes = {
 # main account
 '301237':'和顺科技','301283':'聚胶股份','688093':'世华科技','688191':'智洋创新','002454':'松芝股份',
 '301093':'华兰股份','603966':'法兰泰克','601615':'明阳智能','688186':'广大特材','300658':'延江股份',
 '603202':'天有为','001332':'锡装股份','301110':'青木科技','605598':'上海港湾',
 # agent_auto
 '603409':'汇通控股','301053':'远信工业','688607':'康众科技','301338':'凯格精机',
 # fusion top10
 '300970':'华绿生物','301186':'超达装备','301575':'艾芬达','301590':'优优绿能','300908':'仲景食品',
 '688081':'兴图新科','301538':'骏鼎达',
 # reg10 top10
 '600076':'康欣新材','601949':'中国出版','600103':'青山纸业','603999':'读者传媒','300839':'博汇股份',
 '002679':'福建金森','603618':'杭电股份','301259':'艾布鲁','603900':'莱绅通灵','688300':'联瑞新材',
 # center top10
 '000926':'福星股份','603583':'捷昌驱动','002933':'新兴装备','300073':'当升科技','300879':'大叶股份',
 '003003':'天元股份','300948':'冠中生态','600980':'北矿科技','300837':'浙矿股份','000536':'华映科技',
 # dual top10
 '001238':'浙江正特','300881':'盛德鑫泰','300854':'中兰环保','301636':'泽润新能','688217':'睿昂基因',
 '605056':'咸亨国际','688557':'兰剑智能','301512':'智信精密',
 # dual big positions
 '002531':'天顺风能','300905':'宝丽迪','688486':'龙迅股份','301500':'飞南资源','002738':'中矿资源',
}
inlist = ",".join(f"'{c}'" for c in codes)
q2 = f"""
WITH h AS (
  SELECT left(ts_code,6) code, trade_date, open, high, low, close, vol, pct_chg,
         ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn
  FROM daily WHERE left(ts_code,6) IN ({inlist}) AND trade_date >= '20260715'
), h2 AS (
  SELECT *, MAX(high) OVER (PARTITION BY code ORDER BY rn ROWS BETWEEN 1 FOLLOWING AND 3 FOLLOWING) prev_hi
  FROM h
), last AS (SELECT * FROM h2 WHERE rn <= 21)
SELECT code,
  MAX(CASE WHEN rn=1 THEN close END) px,
  MAX(CASE WHEN rn=1 THEN pct_chg END) today,
  ROUND(SUM(CASE WHEN rn<=5 THEN pct_chg END),1) chg5,
  ROUND(SUM(CASE WHEN rn<=10 THEN pct_chg END),1) chg10,
  ROUND(MAX(high),2) hi20,
  ROUND(MIN(low),2) lo20,
  ROUND(AVG(CASE WHEN rn<=20 THEN close END),2) ma20,
  ROUND(MAX(CASE WHEN rn=1 THEN vol END) / AVG(vol),2) volratio,
  SUM(CASE WHEN rn<=3 AND pct_chg>0 THEN 1 ELSE 0 END) up3,
  SUM(CASE WHEN rn<=3 AND pct_chg<0 THEN 1 ELSE 0 END) dn3,
  MAX(CASE WHEN rn<=10 AND prev_hi IS NOT NULL AND open > prev_hi THEN 1 ELSE 0 END) gap10
FROM last GROUP BY code ORDER BY code
"""
rows = {r[0]: r for r in con.execute(q2).fetchall()}
print("\n=== STOCK PATTERN (code,name,px,today%,chg5,chg10,hi20,lo20,ma20,volX20avg,up3,dn3,gap10) ===")
for c, n in codes.items():
    r = rows.get(c)
    if not r:
        print(c, n, "NO DATA"); continue
    px, today, chg5, chg10, hi20, lo20, ma20, volr, up3, dn3, gap = [float(x) if x is not None else None for x in r[:11]]
    dev20 = (px/ma20-1)*100 if ma20 else None
    fromhi = (px/hi20-1)*100 if hi20 else None
    print(f"{c} {n} px={px} td={today:+.1f}% 5d={chg5:+.1f}% 10d={chg10:+.1f}% hi20={hi20}({fromhi:+.1f}%) lo20={lo20} MA20={ma20}({dev20:+.1f}%) volX={volr} up3={up3} dn3={dn3} gap10={gap}")
con.close()
