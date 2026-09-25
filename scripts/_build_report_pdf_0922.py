# -*- coding: utf-8 -*-
# A-Quant 盘后报告 PDF 排版（2026-09-22 报告）
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, PageBreak, KeepTogether,
                                HRFlowable)

pdfmetrics.registerFont(TTFont("YH", "/System/Library/Fonts/STHeiti Light.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("YH-Bold", "/System/Library/Fonts/STHeiti Medium.ttc", subfontIndex=0))
pdfmetrics.registerFontFamily("YH", normal="YH", bold="YH-Bold", italic="YH", boldItalic="YH-Bold")

INK      = colors.HexColor("#1a2332")
SUB      = colors.HexColor("#5a6678")
LINE     = colors.HexColor("#d8dee8")
BG       = colors.HexColor("#f4f6f9")
RED      = colors.HexColor("#c0392b")   # A股约定：涨=红
GREEN    = colors.HexColor("#1e8449")   # 跌=绿
ACCENT   = colors.HexColor("#1f4e79")
GOLD     = colors.HexColor("#8a6d1a")
WARN_BG  = colors.HexColor("#fdf3e7")
CARD_BG  = colors.HexColor("#eef2f8")

def S(name, size, color=INK, bold=False, leading=1.55, sb=0, sa=0, align=TA_JUSTIFY, indent=0):
    return ParagraphStyle(name, fontName="YH-Bold" if bold else "YH", fontSize=size,
                          textColor=color, leading=size*leading, spaceBefore=sb,
                          spaceAfter=sa, alignment=align, firstLineIndent=indent)

st_body   = S("body", 9.2, INK, sa=5)
st_sec    = S("sec", 14, colors.white, bold=True, align=0)
st_sub    = S("sub", 11.5, ACCENT, bold=True, sb=10, sa=4, align=0)
st_small  = S("small", 8, SUB, leading=1.5)
st_judge  = S("judge", 9.6, INK, leading=1.6, sa=4)
st_cover_t= S("ct", 26, colors.white, bold=True, align=0)
st_cover_s= S("cs", 12, colors.HexColor("#cdd9ea"), align=0)
st_tag    = S("tag", 8.5, colors.white, bold=True, align=0)

W, H = A4
L, Rm = 18*mm, 18*mm
CW = W - L - Rm

def esc(t):
    t = t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    # 涨跌着色：+x% 红 / -x% 绿（只染百分比与明确金额，避免误染代码/日期）
    t = re.sub(r"(?<![\w.])\+(\d[\d,.]*%)", r'<font color="#c0392b">+\1</font>', t)
    t = re.sub(r"(?<![\w.])-(\d[\d,.]*%)", r'<font color="#1e8449">-\1</font>', t)
    t = re.sub(r"([\d,.]+万?)元(?=)", lambda m: m.group(0), t)
    return t

def bd(t): return Paragraph(esc(t), st_body)

def secbar(letter, title):
    tb = Table([[Paragraph(f"{letter}", st_cover_s), Paragraph(title, st_sec)]],
               colWidths=[10*mm, CW-10*mm], rowHeights=[11*mm])
    tb.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),ACCENT),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(0,0),5), ("LEFTPADDING",(1,0),(1,0),2),
        ("LINEBELOW",(0,0),(-1,-1),0.6,GOLD),
    ]))
    return [Spacer(1,10), tb, Spacer(1,8)]

def minitable(header, rows, colw, aligns=None, zebra=True, fontsize=8.2):
    data = [[Paragraph(f"<b>{h}</b>", S(f"h{i}", fontsize, colors.white, bold=True, align=0)) for i,h in enumerate(header)]]
    for r in rows:
        data.append([Paragraph(esc(str(c)), S(f"c{i}", fontsize, align=(aligns[i] if aligns else 0))) for i,c in enumerate(r)])
    t = Table(data, colWidths=colw, repeatRows=1)
    style = [("BACKGROUND",(0,0),(-1,0),ACCENT),
             ("GRID",(0,0),(-1,-1),0.4,LINE),
             ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
             ("TOPPADDING",(0,0),(-1,-1),3.2),("BOTTOMPADDING",(0,0),(-1,-1),3.2),
             ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]
    if zebra:
        for i in range(1,len(data)):
            if i%2==0: style.append(("BACKGROUND",(0,i),(-1,i),BG))
    t.setStyle(TableStyle(style))
    return t

def callout(title, body, bg=WARN_BG, bar=GOLD):
    inner = [Paragraph(esc(f"**{title}**"), S("cot",9.5,INK,bold=True,sa=2,align=0)),
             Paragraph(esc(body), S("cob",8.8,INK,leading=1.5))]
    t = Table([[inner]], colWidths=[CW])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),bg),
        ("LINEBEFORE",(0,0),(0,-1),2.2,bar),
        ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    return t

# ---------- 封面 ----------
def cover():
    band_h = 46*mm
    inner = [[Paragraph("A-Quant 盘后综合报告", st_cover_t)],
             [Paragraph("2026-09-22（周二）· 信号日 0922 → 执行日 0923", st_cover_s)],
             [Spacer(1,6)],
             [Paragraph("定调：指数横住、个股退潮 —— 修复型普涨第三天正式中断，小盘未死，切为少数主线的挤压行情",
                        S("lead",10.5,colors.HexColor("#e8eef7"),leading=1.5))]]
    band = Table(inner, colWidths=[CW-16*mm], rowHeights=[None,None,None,None])
    band.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#15243b")),
        ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10),
        ("TOPPADDING",(0,0),(0,0),12),("BOTTOMPADDING",(0,-1),(-1,-1),12),
        ("LINEBELOW",(0,-1),(-1,-1),1.5,GOLD),
    ]))
    kpi = Table([[
        Paragraph('<font name="YH-Bold" size=15 color="#c0392b">+19.74%</font><br/><font name="YH" size=7.5 color="#cdd9ea">主账户累计收益</font>', st_cover_s),
        Paragraph('<font name="YH-Bold" size=15 color="#c0392b">+0.85%</font><br/><font name="YH" size=7.5 color="#cdd9ea">主账户当日</font>', st_cover_s),
        Paragraph('<font name="YH-Bold" size=15 color="#7fd4a8">-0.09%</font><br/><font name="YH" size=7.5 color="#cdd9ea">中证1000当日</font>', st_cover_s),
        Paragraph('<font name="YH-Bold" size=15 color="#f0e6c8">43%</font><br/><font name="YH" size=7.5 color="#cdd9ea">上涨家数占比（昨82%）</font>', st_cover_s),
        Paragraph('<font name="YH-Bold" size=15 color="#f0e6c8">2.15万亿</font><br/><font name="YH" size=7.5 color="#cdd9ea">两市成交（+5.2%）</font>', st_cover_s),
    ]], colWidths=[CW/5]*5)
    kpi.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),CARD_BG),
        ("BOX",(0,0),(-1,-1),0.5,LINE),("INNERGRID",(0,0),(-1,-1),0.5,colors.white),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),8),
    ]))
    return [band, Spacer(1,8), kpi]

# ---------- 正文数据 ----------
JUDGE = [
 "修复未死但进入「二选一」关口：明日涨占比不回 50% 即确认反抽夭折——错了就是普涨重启。",
 "本周账户最大隐患是华兰股份（15% 仓位＋尾盘诱多预警），不是任何当前亏损票。",
 "reg10 进入失效观察期（IC 5日均 −0.064）：若明日再负，暂停一切 10d 类新仓。",
 "明日只做一个动作：中兰环保（三榜共振、位置最低）在 15.3 下方低吸，其余不动。",
 "NAS 备份 9 天断档，09-27 首次看门狗考验若再失败需人工介入——若成功，撤回此风险披露。",
]

ACCT_ROWS = [
 ["智洋创新 688191","+7,850 元","+7.3%","连涨第7日创近期新高，趋势延续非反抽；与 center_dual 唯一交叉验证仓位"],
 ["艾芬达 301575","+3,770 元","——","建仓日即涨"],
 ["青木科技 301110","+1,860 元","——","贡献第三"],
 ["康欣新材 600076","−1,615 元","——","高位放量阴跌，是兑现不是破位"],
 ["上海港湾 605598","−1,089 元","−6.9%","唯一亏损票，阴跌型；建议反弹 25.5-26 主动减半"],
 ["锡装股份 001332","−936 元","——","小幅回吐"],
]

NAV_ROWS = [
 ["CMMR+融合","+0.35%","+33.42%","+23.76%","「低分位+高斜率」选票天然回避今日杀跌高位拥挤票"],
 ["CMMR独立","+0.26%","+27.56%","+17.91%","同上，CMMR 系继续碾压"],
 ["10d独立","+0.96%","+5.52%","+1.25%","当日最强，全靠涨停矩阵（新华百货/联合精密）；新建户待观察"],
 ["中枢Top10","+0.16%","+13.08%","+10.06%","稳"],
 ["中枢+三模型","+0.18%","−0.83%","−3.66%","最弱：40d 腿押在光伏/电气超跌段，修复期弹性不足"],
 ["Agent全权","−0.59%","+0.79%","−1.34%","唯一跑输：昨日 82% 普涨日满仓追高，今日分化日吃回吐"],
 ["CMMR+clf门票","+0.23%","——","——","0922 新建，NAV 1,002,272，待观察"],
]

IC_ROWS = [
 ["fusion 融合","+0.031","弱正","只信排序方向"],
 ["reg10","−0.064","转负走弱","进入失效观察期；连续 8 日负则停 10d 类加仓"],
 ["reg20","+0.010","平","——"],
 ["reg40","+0.033","撑住融合分","当前波段可信"],
 ["center 中枢","+0.152","强势","当前波段可信"],
 ["center_dual","+0.061","正","——"],
]

RANK_CMMR = [
 ["深中华A 000017","100","5日+12.8% 但尾盘诱多 → 明日不追，回 7.8 下方再看"],
 ["兴业银锡 000426","100","布林12%、5日−3.1% 仍跌 → 开盘续跌>3% 按四层保护停买"],
 ["京粮控股 000505","100","涨后缩量回踩 → 低吸 6.6 附近"],
 ["红棉股份 000523","100","±10% 妖性高波动 → 放弃"],
 ["大连友谊 000679","100","布林61% 稳步爬 → 低吸 6.4-6.5"],
 ["博源化工 000683","100","布林13% 阴跌 → 放弃"],
 ["中水渔业 000798","100","昨+10% 今平量缩 → 观望"],
 ["法尔胜 000890","100","榜票=账户实仓(+0.6%) → 持有不加"],
 ["欢瑞世纪 000892","100","连+2 放量 → 回调 4.6 低吸"],
 ["登海种业 002041","100","慢牛爬 → 回调 MA10 低吸"],
]

RANK_FUSION = [
 ["苏利股份 603585","9.7 ★CMMR+榜1","布林33%、距20日高−10.7% 健康回调位 → 低吸 10.1-10.5，高开>2%放弃"],
 ["中兰环保 300854","9.3 ★三榜共振","连+3日温和放量 → 首选低吸标的，14.8-15.3"],
 ["金陵体育 300651","8.9 ★","连+5日量比1.5 趋势最顺 → 回调MA10(16.0)介入，追高需突破17.2确认"],
 ["华图山鼎 300492","8.8","0916/0921/0922 三根放量阳启动 → 等突破 MA20 23.2 再上"],
 ["纬德信息 688171","8.7","高波动布林23% → 观望"],
 ["苏文电能 300982","8.3 ★","center_dual 实仓持有中(−2.8%) → 模拟盘持有验证；新仓低吸 13.8-14.2"],
 ["腾远钴业 301219","7.8","布林30% 低位横盘 → 观望"],
 ["优优绿能 301590","7.7 ★持仓","高位横盘消化 → 持有，回踩MA10(68)不破不卖"],
 ["艾布鲁 301259","7.6","5日+10.4% 短线偏热 → 回调MA10低吸不追"],
 ["复洁科技 688335","7.6","低位无量 → 观望"],
]

RANK_FUSION_PLUS = [
 ["苏利股份","130.0","★本榜榜1，与三模型榜交叉，同上低吸"],
 ["百川畅银","129.6","回踩 MA10 一线 10.3 低吸"],
 ["美农生物","129.0","回踩 11.8 一线低吸"],
 ["凤形股份","128.8","同纪律：高开>2%放弃、只回踩MA10低吸"],
 ["力盛体育","128.8","同上"],
 ["启迪设计","128.7","回踩 9.4 一线低吸"],
 ["维业股份","128.7","回踩 7.0 一线低吸"],
 ["天元股份","128.6","回踩 10.8 一线低吸"],
 ["红墙股份","128.3","斜率+0.078 全榜最陡，可略积极"],
 ["威奥股份","128.3","同纪律"],
]

RANK_10D = [
 ["华瓷股份 001216","7连板 5日+61%","布林120%+ 极端超买 → 一律不追（账户按 gap 补仓规则天然回避）"],
 ["华远控股 600743","5板","极端超买 → 不追"],
 ["荣丰控股 000668","连两日−8%/−10%","放量破位 → 停买，等止跌"],
 ["新华文轩 601811","5板","极端超买 → 不追"],
 ["新华传媒 600825","3板","极端超买 → 不追"],
 ["和顺科技 301237","★持仓 +7.5%","今日−1.1% 正常回踩 → 持有"],
 ["哈森股份 603958","昨涨停今缩量+0.9%","账户(+7.9%)持有，新仓不追（昨报「触23.8」有误，现价18.53）"],
 ["芒果超媒 300413","布林62%","观望"],
 ["经纬辉开 300120","0918大涨后消化","回调 MA10"],
 ["时代出版 600551","量比1.7 温和加速","回调 7.6 低吸"],
]

RANK_CENTER = [
 ["整榜共性","贴近日高缓爬（距20日高多在−5%内）：中枢票只低吸不追高"],
 ["渝开发 000514","连+5日布林93% 偏热，除外需谨慎"],
 ["中兰环保 300854 ★","双榜共振优先"],
 ["中自科技 688737 ★","双榜共振优先"],
]

RANK_CENTER3 = [
 ["中兰环保 ★★★","唯一三榜共振，明日唯一动作标的"],
 ["金陵体育 ★★ / 中自科技 ★★ / 苏文电能 ★★","共振票，回踩介入"],
 ["科大国创·绿康·瀛通·富瑞·谱尼","5/10 今日跳空高开 → 回踩缺口上沿再介入"],
 ["合金投资 000633","距高仅−5.3% 相对健康"],
]

CAL_ROWS = [
 ["中枢+三模型","仅剩 1 个交易日 → 后日重评","watchlist 已挂 5 候选（苏利/中兰/金陵/纬德/腾远）"],
 ["10d独立","剩 5","——"],["CMMR+","剩 5","——"],["中枢版","剩 7","——"],
 ["CMMR独立","剩 8","——"],["CMMR+clf","剩 9","新建户"],
 ["Agent全权","agent 自主择时","——"],
]

def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("YH", 7)
    canvas.setFillColor(SUB)
    canvas.drawString(L, H-11*mm, "A-Quant · 盘后综合报告 · 2026-09-22")
    canvas.drawRightString(W-Rm, H-11*mm, "数据源：tushare / ledger 权威库对拍（修正版）")
    canvas.setStrokeColor(LINE); canvas.setLineWidth(0.4)
    canvas.line(L, H-12.5*mm, W-Rm, H-12.5*mm)
    canvas.line(L, 13*mm, W-Rm, 13*mm)
    canvas.drawString(L, 9*mm, "Nous · Hermes 生成")
    canvas.drawRightString(W-Rm, 9*mm, f"第 {doc.page} 页")
    canvas.restoreState()

doc = BaseDocTemplate("/Users/zantao/Desktop/A-Quant盘后报告_20260922.pdf",
                      pagesize=A4, leftMargin=L, rightMargin=Rm,
                      topMargin=17*mm, bottomMargin=17*mm,
                      title="A-Quant 盘后综合报告 2026-09-22", author="Hermes")
frame = Frame(L, 17*mm, CW, H-17*mm-16*mm, id="main")
doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=header_footer)])

story = []
story += cover()

# 摘要
story.append(Spacer(1,10))
story.append(Paragraph("今 日 要 点", st_sub))
story.append(minitable(["#","要点"], [[str(i+1), j] for i,j in enumerate(JUDGE)],
                       [8*mm, CW-8*mm], aligns=[1,0], fontsize=8.8))

# ============ A 部分 ============
story += secbar("A", "今日复盘")

story.append(Paragraph("1 · 大盘与风格", st_sub))
story.append(bd("维持「本轮中证1000反弹是超跌修复、不是反转」。今日四条依据："))
story.append(minitable(["维度","读数","解读"], [
 ["量能","2.15万亿（+5.2%）","放量但涨占比从昨 82% 崩到 43% —— 出货式放量，不是入场式放量"],
 ["宽度","涨占比 43%","显著低于 20 日中位 54%；指数（中证1000 −0.09%）与个股宽度严重背离"],
 ["风格","小盘 5日+4.3% vs 上证50 +2.3%","上证50 +0.43% 微跑输中证1000，小盘只是歇脚，风格未切换"],
 ["板块","塑料+8.4% 出版+3.7% 专用机械+2.3%","连续强势主线；昨日领涨的地产/医药今日退潮 = 高低切换成立"],
], [16*mm, 40*mm, CW-56*mm], fontsize=8.3))
story.append(Spacer(1,4))
story.append(bd("**若我错**：明日涨占比回 50%+ 且成交再放量，则普涨卷土重来，我认错。"))

story.append(Paragraph("2 · 主账户（总资产 1,197,372 元 · 当日 +0.85% · 累计 +19.74%）", st_sub))
story.append(minitable(["持仓","当日贡献","备注","点评"], ACCT_ROWS,
                       [34*mm, 22*mm, 18*mm, CW-74*mm], fontsize=8.3))
story.append(Spacer(1,4))
story.append(bd("结论线索：①贡献全部集中在电气设备/AI 应用方向，持仓 alpha 依赖智洋一只票——它是主账户与 center_dual 的**唯一交叉验证仓位**（两边同持，center_dual 内 +14.5%）；②华兰股份 15% 第一大仓位今日被**尾盘诱多组合**预警（开跌−1.9% + VWAP+0.5% + 振幅7.9%），是本周账户最大隐患；③风控临近止盈：聚胶 +2.5%、延江 +3.4%、松芝 +3.1%。距止损最近：**天有为 +3.0%、法兰泰克 +4.1%、明阳智能 +5.3%**。"))

story.append(Paragraph("3 · 账户 vs 基准（市场 −0.09%）· 策略账户对比", st_sub))
story.append(minitable(["策略账户","当日","累计","超额(累计)","点评"], NAV_ROWS,
                       [26*mm, 16*mm, 18*mm, 20*mm, CW-80*mm], fontsize=8.3))

story.append(Paragraph("4 · 信号质量（分模型 IC · 近5日均值，ic_daily/signals 复算）", st_sub))
story.append(minitable(["模型","IC 5日均","状态","处置"], IC_ROWS,
                       [24*mm, 20*mm, 24*mm, CW-68*mm], fontsize=8.3))
story.append(Spacer(1,4))
story.append(bd("三模型 Top10 次日超额近5日 +0.46%（正 3/5，0921 榜 −0.7% 今天吃负）；CMMR/CMMR+ 次日超额 −0.27%（正 1/5）——CMMR 的 alpha 不在「次日」，在持仓期内滚动换筹，与此前结论一致。**所以：当前波段只信 reg40/中枢排序，reg10 短线预测进入失效观察期。**尾盘预警：华兰股份、深中华A（CMMR榜1号票）诱多组合。"))

story.append(Paragraph("5 · 系统 · 备份 · 今日自主决策", st_sub))
story.append(bd("**全链路 cron** 全绿（数据更新 16:19 → CMMR IC 23:51），无异常。"))
story.append(bd("**备份**：本机 0922 19:51 成功；NAS 最近成功 09-13 13:28，09-20 02:00 尝试失败（SSH 不可达），**已 9 天无 NAS 异地备份**。09-22 已部署 keeper 双级看门狗修复根因（webcron 死 → AAAA 冻结），下周一（09-27 02:00）是修复后首次考验，在此之前风险披露维持「仅本机备份保护」。"))
dec = [
 ["运维","NAS keeper 看门狗部署","webcron 死导致 AAAA 冻结"],
 ["运维","Mac ts_cache_keeper","缓存守护补齐"],
 ["运维","M2 ts_cache_keeper","双机对称"],
 ["规则","检索纪律 skill 修正","空结果先查 search_timeout"],
 ["规则","OPS_FACTS 记录盘中估值假摔机制","record_nav 成本价兜底致 −2.36% 假摔，实为 +1.34%"],
]
story.append(Spacer(1,3))
story.append(KeepTogether([bd("**今日自主决策（DECISIONS.md 09-22，5 条，均运维/规则层）**："),
    minitable(["层","改了什么","依据"], dec, [14*mm, 62*mm, CW-76*mm], fontsize=8.2)]))

story.append(PageBreak())

# ============ B 部分 ============
story += secbar("B", "明日预案（执行日 0923）")

story.append(Paragraph("6 · 大盘验证点", st_sub))
story.append(minitable(["#","验证点","触发 → 动作"], [
 ["①","涨占比 / 成交","回 50%+ 且 ≥2.2 万亿 → 修复延续；跌破 40% + 缩量 → 反抽夭折确认，主账户转「只减不加」"],
 ["②","塑料/出版主线","第 4 日强势 → 主线成立可低吸跟随；断裂 → 回题材轮动"],
 ["③","防守位","中证1000 不回补 7687（0918 收盘缺口）；回补即修复结束"],
], [8*mm, 32*mm, CW-40*mm], fontsize=8.4))

story.append(Paragraph("7 · 逐榜意见（信号日 0922；★=多榜共振）", st_sub))

def rank_block(title, note, rows, note_bold=False):
    out = [KeepTogether([Paragraph(title, S("rt",9.8,GOLD,bold=True,sb=8,sa=3,align=0))])]
    if note: out.append(bd(note))
    out.append(minitable(["代码/名称","分数/状态","意见与操作"], rows,
                         [34*mm, 30*mm, CW-64*mm], fontsize=8.2))
    return out

story += rank_block("三模型融合（40日预测窗口）",
    "口径：40 日预测分。榜单价值集中在头部共振票。", RANK_FUSION)
story += rank_block("CMMR独立（重评 10 日）",
    None, RANK_CMMR)
story += rank_block("CMMR+三模型融合（重评 20 日）",
    "本榜 6/10 今日跳空高开、整榜连+2日启动：全部执行统一纪律——**高开>2%放弃、只回踩MA10低吸**。", RANK_FUSION_PLUS)
story += rank_block("10d独立（reg10_solo 建仓依据榜 · 重评 10 日）",
    "**对照**：reg10_solo 账户持康欣新材（不在今日榜）但持联合精密（昨日榜）——10d 榜与账户持仓日际漂移大，正是 reg10 IC 转负期的正常现象。", RANK_10D)
story += rank_block("中枢版Top10（20-40日窗口 · 名单粘性≠持有窗口）",
    None, RANK_CENTER)
story += rank_block("中枢+三模型（窗口期未知，不得声称40日 · 仅剩1个交易日）",
    None, RANK_CENTER3)

story.append(Spacer(1,6))
story.append(callout("榜间交叉",
 "三模型∩中枢+三模型 = 3 票（中兰/金陵/苏文）；三模型∩CMMR+ = 1 票（苏利）；中枢∩中枢+三模型 = 2 票（中兰/中自）。**中兰环保是唯一三榜共振。**"))

story.append(Paragraph("8 · 调仓日历（明日 0923）", st_sub))
story.append(minitable(["策略账户","距重评","备注"], CAL_ROWS, [30*mm, 45*mm, CW-75*mm], fontsize=8.3))

story.append(Paragraph("9 · 持仓操作", st_sub))
story.append(callout("明日开盘第一盯防：天有为",
 "距止损仅 +3.0%（2.25 收盘距 50.05 止损一步之遥）——开盘跌 >3% 直接触线。第二：法兰泰克（距止损 +4.1%、距止盈 +8.5%）。",
 WARN_BG, RED))
story.append(Spacer(1,5))
story.append(bd("止盈临近三票合计：聚胶 10.5万 + 延江 3.1万 + 松芝 1.8万 ≈ **15.4万 = 总资产 12.9%**，全部挂「触价减半」开关；若明日普涨兑现会集中触发，属计划内。华兰按尾盘诱多预警：**冲高不加仓、跌破 70 减 1/3**。全策略账户无 R7 破线票（最差宇通 −3.4% 未触 0.94 线）。上海港湾主账户 −6.9%：阴跌不触止损（距 23.7 还有 7%），建议明日反弹到 25.5-26 主动减半——这是它与 CMMR/中枢榜入选逻辑都脱钩后的唯一理由。"))
story.append(bd("明晨 7:00 盘前报告看隔夜外盘定开盘倾向；盘中意见引擎每 10 分钟自动盯池，有新意见推 QQ。"))

story.append(Spacer(1,10))
jhead = Table([[Paragraph("我 的 判 断", st_sec)]], colWidths=[CW], rowHeights=[9*mm])
jhead.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#15243b")),
                           ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(0,0),10),
                           ("LINEBELOW",(0,0),(-1,-1),0.6,GOLD)]))
jbody = minitable(["#","判断（次日打分对账）"], [[str(i+1), j] for i,j in enumerate(JUDGE)],
                  [8*mm, CW-8*mm], aligns=[1,0], fontsize=8.8)
story.append(KeepTogether([jhead, Spacer(1,4), jbody]))
story.append(Spacer(1,8))
story.append(Paragraph("关注池共 144 只（策略名单去重 ∪ 全部持仓）。数据来源：tushare.db（只读）/ ledger.db / signals.db，数字已与权威库对拍（修正版）。", st_small))

doc.build(story)
print("PDF_BUILT")
