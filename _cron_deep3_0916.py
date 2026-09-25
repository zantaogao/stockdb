import duckdb, pandas as pd
con = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
codes = {
 '301237':'和顺科技','301283':'聚胶股份','688093':'世华科技','688191':'智洋创新','002454':'松芝股份',
 '301093':'华兰股份','603966':'法兰泰克','601615':'明阳智能','688186':'广大特材','300658':'延江股份',
 '603202':'天有为','001332':'锡装股份','301110':'青木科技','605598':'上海港湾',
 '603409':'汇通控股','301053':'远信工业','688607':'康众科技','301338':'凯格精机',
 '300970':'华绿生物','301186':'超达装备','301575':'艾芬达','301590':'优优绿能','300908':'仲景食品',
 '688081':'兴图新科','301538':'骏鼎达',
 '600076':'康欣新材','601949':'中国出版','600103':'青山纸业','603999':'读者传媒','300839':'博汇股份',
 '002679':'福建金森','603618':'杭电股份','301259':'艾布鲁','603900':'莱绅通灵','688300':'联瑞新材',
 '000926':'福星股份','603583':'捷昌驱动','002933':'新兴装备','300073':'当升科技','300879':'大叶股份',
 '003003':'天元股份','300948':'冠中生态','600980':'北矿科技','300837':'浙矿股份','000536':'华映科技',
 '001238':'浙江正特','300881':'盛德鑫泰','300854':'中兰环保','301636':'泽润新能','688217':'睿昂基因',
 '605056':'咸亨国际','688557':'兰剑智能','301512':'智信精密',
 '002531':'天顺风能','300905':'宝丽迪','688486':'龙迅股份','301500':'飞南资源','002738':'中矿资源',
}
inlist = ",".join(f"'{c}'" for c in codes)
df = con.execute(f"""
SELECT left(ts_code,6) code, trade_date, open, high, low, close, vol, pct_chg
FROM daily WHERE left(ts_code,6) IN ({inlist}) AND trade_date >= '20260715'
ORDER BY code, trade_date
""").df()
for c, n in codes.items():
    d = df[df.code == c].reset_index(drop=True)
    if len(d) < 5:
        print(c, n, "NO DATA"); continue
    px = d.close.iloc[-1]; today = d.pct_chg.iloc[-1]
    chg5 = d.pct_chg.tail(5).sum(); chg10 = d.pct_chg.tail(10).sum()
    hi20 = d.high.tail(20).max(); lo20 = d.low.tail(20).min()
    ma20 = d.close.tail(20).mean()
    volr = d.vol.iloc[-1] / d.vol.tail(20).mean()
    up3 = int((d.pct_chg.tail(3) > 0).sum()); dn3 = int((d.pct_chg.tail(3) < 0).sum())
    # gap up above prior 3-day high in last 10 days
    gap = 0
    for i in range(max(1, len(d)-10), len(d)):
        if d.open.iloc[i] > d.high.iloc[max(0,i-3):i].max(): gap += 1
    # limit-up in last 20 days?
    lu = int((d.pct_chg.tail(20) >= 9.5).sum())
    print(f"{c} {n} px={px:.2f} td={today:+.1f}% 5d={chg5:+.1f}% 10d={chg10:+.1f}% "
          f"距hi20={(px/hi20-1)*100:+.1f}% 距lo20={(px/lo20-1)*100:+.1f}% MA20偏离={(px/ma20-1)*100:+.1f}% "
          f"volX={volr:.1f} up3={up3} dn3={dn3} gap10={gap} 涨停20d={lu}")
con.close()
