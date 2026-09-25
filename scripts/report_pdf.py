#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用报告 PDF 排版器：报告 txt（markdown 子集）→ A-Quant 版式 PDF（09-22 桌面稿同款）。
用法: report_pdf.py <报告.txt> <输出.pdf> [封面副标题]
支持语法（cron agent 写报告时遵守的约定）：
  首行           报告标题（自动加 "A-Quant " 前缀进封面）
  【今日要点】节   编号要点 → 封面下方金色要点卡
  A｜1 · 标题     节标题（A/B 字母段 → 带字母的分节蓝条；无字母则纯编号蓝条）
  | 表头 | ... |   markdown 表格（分隔行 |---| 自动识别）
  > 引用行        callout 警示卡（**加粗**标题 + 正文）
  **x**           加粗；+x% 自动红、-x% 自动绿（A股配色）
  1. 2. 3.        编号列表
  其余            正文段落
封面 KPI 卡：从正文第一张 markdown 表自动提取（≤5 列全取），提取后该表不再进正文。"""
import base64
import os
import re
import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
                                Spacer, Table, TableStyle, KeepTogether, HRFlowable)

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

W, H = A4
LM, RM = 18*mm, 18*mm
CW = W - LM - RM

_section_counter = {"n": 0}

def esc(t):
    t = t.replace("&", "&amp;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w.])\+(\d[\d,.]*%)", r'<font color="#c0392b">+\1</font>', t)
    t = re.sub(r"(?<![\w.])-(\d[\d,.]*%)", r'<font color="#1e8449">-\1</font>', t)
    return t

def bd(t): return Paragraph(esc(t), st_body)

def secbar(letter, title):
    if letter:
        cells = [Paragraph(letter, st_cover_s), Paragraph(title, st_sec)]
        widths = [10*mm, CW-10*mm]
    else:
        cells = [Paragraph(title, st_sec)]
        widths = [CW]
    tb = Table([cells], colWidths=widths, rowHeights=[11*mm])
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), ACCENT),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (0,0), 5),
        ("LINEBELOW", (0,0), (-1,-1), 0.6, GOLD),
    ]))
    return [Spacer(1, 10), tb, Spacer(1, 8)]

def minitable(header, rows, colw=None, aligns=None, zebra=True, fontsize=8.2):
    ncol = len(header)
    if colw is None:
        colw = [CW/ncol]*ncol
    data = [[Paragraph(f"<b>{esc(h)}</b>", S(f"h{i}", fontsize, colors.white, bold=True, align=0))
             for i, h in enumerate(header)]]
    for r in rows:
        r = list(r) + [""]*(ncol-len(r))
        data.append([Paragraph(esc(str(c)), S(f"c{i}", fontsize, align=(aligns[i] if aligns else 0)))
                     for i, c in enumerate(r[:ncol])])
    t = Table(data, colWidths=colw, repeatRows=1)
    style = [("BACKGROUND", (0,0), (-1,0), ACCENT),
             ("GRID", (0,0), (-1,-1), 0.4, LINE),
             ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
             ("TOPPADDING", (0,0), (-1,-1), 3.2), ("BOTTOMPADDING", (0,0), (-1,-1), 3.2),
             ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4)]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0,i), (-1,i), BG))
    t.setStyle(TableStyle(style))
    return t

def callout(title, body, bg=WARN_BG, bar=GOLD):
    inner = [Paragraph(esc(f"**{title}**"), S("cot", 9.5, INK, bold=True, sa=2, align=0)),
             Paragraph(esc(body), S("cob", 8.8, INK, leading=1.5))]
    t = Table([[inner]], colWidths=[CW])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), bg),
        ("LINEBEFORE", (0,0), (0,-1), 2.2, bar),
        ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return t


# ───────────────────────── parsing ─────────────────────────

def parse_table(lines, i):
    """lines[i] 是表头行。返回 (header, rows, next_i)。"""
    def split_row(s):
        s = s.strip().strip("|")
        return [c.strip() for c in s.split("|")]
    header = split_row(lines[i])
    j = i + 1
    if j < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[j]) and "-" in lines[j]:
        j += 1  # 跳过分隔行
    rows = []
    while j < len(lines) and "|" in lines[j] and lines[j].strip():
        rows.append(split_row(lines[j]))
        j += 1
    return header, rows, j


def _normalize_lines(lines):
    """归一化 agent 生成的报告：段落尾粘连 markdown 表格时拆行（剥表逻辑按行匹配）。"""
    out = []
    for ln in lines:
        idx = ln.find("|")
        # 段落中 | 前还有文字 → 表格文字被误粘进段落，拆到独立行
        if idx > 0 and not ln.startswith("|") and not ln.lstrip().startswith(">"):
            head, tail = ln[:idx].rstrip(), ln[idx:]
            looks_like_table = tail.rstrip().endswith("|") and tail.count("|") >= 4
            if looks_like_table:
                if head:
                    out.append(head)
                # tail 里可能混有 |---| 分隔行与数值行，也逐段拆开
                parts = re.split(r"(\|[-:| ]+\|)", tail)
                for p in parts:
                    p = p.strip()
                    if p:
                        out.append(p)
                continue
        out.append(ln)
    return out


def build(txt_path, pdf_path, subtitle=""):
    text = open(txt_path, encoding="utf-8").read().strip()
    lines = _normalize_lines(text.split("\n"))

    # 标题 = 第一行非空
    title = lines[0].strip().lstrip("#").strip()
    body_lines = lines[1:]

    # 提取【今日要点】节（标题行 + 编号条目）→ 封面卡
    points = []
    out = []
    it = iter(range(len(body_lines)))
    k = 0
    in_points = False
    while k < len(body_lines):
        ln = body_lines[k]
        if re.match(r"^[【\[]?今日要点[】\]]?\s*$", ln.strip()):
            in_points = True
            k += 1
            continue
        if in_points:
            m = re.match(r"^\s*(\d+)[\.、\)）]\s*(.+)$", ln)
            if m:
                points.append(m.group(2).strip())
                k += 1
                continue
            if ln.strip() == "" :
                # 要点节内允许空行，但遇到非条目即出节
                if k+1 < len(body_lines) and re.match(r"^\s*\d+[\.、\)）]", body_lines[k+1]):
                    k += 1
                    continue
            in_points = False
            continue  # 要点节的首个非条目行交给主解析（可能是节标题）
        out.append(ln)
        k += 1
    body_lines = out

    # 封面 KPI：正文第一张表 ≤5 列 且行数为1（单行数值表）→ KPI 卡
    kpis = []
    kpi_limit = next((i for i, l in enumerate(body_lines)
                      if re.match(r"^[A-Z]\s*[｜|]\s*\d", l.strip())), len(body_lines))
    for idx in range(kpi_limit):
        if body_lines[idx].strip().startswith("|"):
            header, rows, nxt = parse_table(body_lines, idx)
            if len(header) <= 6 and len(rows) == 1 and len("".join(rows[0])) < 200:
                kpis = list(zip(header, rows[0]))
                body_lines = body_lines[:idx] + body_lines[nxt:]
            break
    # 同一张表若在正文以散文形式重贴（agent 粘贴失误），剥掉散文字面量，保留真表
    # 散文版可能折行（表头与数值各折多行），故在节边界之间做滑窗匹配
    if kpis:
        def _norm(row): return ("|" + "|".join(c.strip() for c in row) + "|").replace(" ", "")
        kpi_header = _norm([h for h, _ in kpis])
        kpi_values = _norm([v for _, v in kpis])
        sep_re = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
        sec_re = re.compile(r"^[A-Z]\s*[｜|]\s*\d")
        # 按节边界切块
        bounds, k = [0], 0
        for i, l in enumerate(body_lines):
            if sec_re.match(l.strip()):
                bounds.append(i)
        bounds.append(len(body_lines))
        cleaned = []
        for a, b in zip(bounds, bounds[1:]):
            seg = body_lines[a:b]
            # 段内：把 "|...|" 及其后紧跟的 ---/数值 行折叠为逻辑行，若命中 KPI 内容则整段丢弃
            j = 0
            while j < len(seg):
                l = seg[j]
                if l.strip().startswith("|") and not sep_re.match(l):
                    lines_block, m = [l], j + 1
                    hit = _norm([l.strip().strip("|").strip()]) == kpi_header
                    while m < len(seg) and (seg[m].strip().startswith("|") or sep_re.match(seg[m])):
                        _row = seg[m].strip()
                        if _row.startswith("|") and _norm([_row.strip("|").strip()]) == kpi_values:
                            hit = True
                        lines_block.append(seg[m]); m += 1
                    if hit:
                        j = m
                        continue
                    cleaned.extend(lines_block); j = m
                    continue
                cleaned.append(l); j += 1
        body_lines = cleaned

    # ── 文档 ──
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("YH", 7.5)
        canvas.setFillColor(SUB)
        canvas.drawString(LM, 12*mm, title)
        canvas.drawRightString(W-RM, 12*mm, f"第 {canvas.getPageNumber()} 页")
        canvas.restoreState()

    def _num(v):
        return float(v) if isinstance(v, str) else v
    doc = BaseDocTemplate(str(pdf_path), pagesize=A4,
                          leftMargin=_num(LM), rightMargin=_num(RM),
                          topMargin=_num(18*mm), bottomMargin=_num(20*mm),
                          title=title)
    frame = Frame(LM, 20*mm, CW, H-38*mm, id="main")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=footer)])

    story = []
    # 封面头带
    band_inner = [[Paragraph(esc(("A-Quant " + title)[:60]), st_cover_t)]]
    if subtitle:
        band_inner.append([Paragraph(esc(subtitle), st_cover_s)])
    band = Table(band_inner, colWidths=[CW-16*mm])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#15243b")),
        ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (0,0), 12), ("BOTTOMPADDING", (0,-1), (-1,-1), 12),
        ("LINEBELOW", (0,-1), (-1,-1), 1.5, GOLD),
    ]))
    story.append(band)

    if kpis:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        n = len(kpis)
        cell_w = CW/n - 16
        def kpi_font(v):
            for fs in (14, 12.5, 11, 9.5, 8.5):
                if stringWidth(v, "YH-Bold", fs) <= cell_w:
                    return fs
            return 8
        kpi_cells = [Paragraph(
            f'<font name="YH-Bold" size={kpi_font(v)} color="{(RED if v.strip().startswith("+") else GREEN if v.strip().startswith("-") else colors.HexColor("#f0e6c8")).hexval().replace("0x","#")[0:7]}">{esc(v)}</font>'
            f'<br/><font name="YH" size=7.5 color="#cdd9ea">{esc(h)}</font>', st_cover_s)
            for h, v in kpis]
        kpi = Table([kpi_cells], colWidths=[CW/n]*n)
        kpi.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#15243b")),
            ("LINEABOVE", (0,0), (-1,0), 0.4, colors.HexColor("#2c3e57")),
            ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 10),
            ("LEFTPADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(kpi)

    if points:
        story.append(Spacer(1, 8))
        ptitle = Paragraph("<b>今 日 要 点</b>", S("pt", 12, GOLD, align=0))
        prow = [[ptitle]]
        plist = [Paragraph(esc(f"**{i+1}**　{x}"), st_judge) for i, x in enumerate(points)]
        prow.append([plist])
        pt = Table(prow, colWidths=[CW])
        pt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#fbf7ec")),
            ("LINEBELOW", (0,-1), (-1,-1), 0.6, GOLD),
            ("LEFTPADDING", (0,0), (-1,-1), 10), ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING", (0,0), (0,0), 8), ("BOTTOMPADDING", (0,0), (0,0), 4),
            ("BOTTOMPADDING", (0,-1), (-1,-1), 8),
        ]))
        story.append(pt)

    # ── 正文流 ──
    i, n = 0, len(body_lines)
    while i < n:
        raw = body_lines[i]
        ln = raw.strip()
        if not ln:
            i += 1
            continue
        # 节标题: A｜1 · 标题 / A|... / 纯「1 · 标题」
        m = re.match(r"^([A-Z])\s*[｜|]\s*(.+)$", ln)
        if m:
            story.extend(secbar(m.group(1), m.group(2).strip())); i += 1; continue
        m = re.match(r"^(\d{1,2})\s*[·・.]\s*(\S.*)$", ln)
        if m and len(ln) < 40 and not ln.rstrip().endswith(("。", "，", "；", "：")):
            story.extend(secbar(None, f"{m.group(1)} · {m.group(2)}")); i += 1; continue
        # 【xxx】独立标题行 → 子标题
        m = re.match(r"^[【\[](.{2,20})[】\]]\s*$", ln)
        if m and not ln.rstrip().endswith(("。", "，", "；")):
            story.append(Spacer(1, 6))
            story.append(Paragraph(esc(m.group(1)), st_sub)); i += 1; continue
        # 表格
        if ln.startswith("|"):
            header, rows, nxt = parse_table(body_lines, i)
            if rows or header:
                ncol = len(header)
                # 列宽：长文本列加权
                lens = [max([len(str(header[c]))] + [len(str(r[c])) if c < len(r) else 0 for r in rows]) for c in range(ncol)]
                tot = sum(lens) or 1
                colw = [max(14*mm, CW*l/tot) for l in lens]
                s = sum(colw); colw = [c*CW/s for c in colw]
                story.append(Spacer(1, 4))
                story.append(minitable(header, rows, colw))
                story.append(Spacer(1, 4))
            i = nxt; continue
        # callout
        if ln.startswith(">"):
            cap = ln.lstrip("> ").strip()
            i += 1
            cont = []
            while i < n and body_lines[i].strip().startswith(">"):
                cont.append(body_lines[i].lstrip("> ").strip()); i += 1
            m = re.match(r"^\*\*(.+?)\*\*[:：]?\s*(.*)$", cap, re.S)
            if m:
                story.append(callout(m.group(1), (m.group(2) + (" " + " ".join(cont) if cont else "")).strip()))
            else:
                story.append(callout("注意", " ".join([cap] + cont)))
            story.append(Spacer(1, 4)); continue
        # 编号列表
        m = re.match(r"^(\d{1,2})[\.、\)）]\s+(.+)$", ln)
        if m and not m.group(2)[:6].isdigit():
            story.append(Paragraph(esc(f"<b>{m.group(1)}.</b>　{m.group(2)}"), st_judge)); i += 1; continue
        # 普通段落（连续非空行合并为一段）
        para = [ln]
        i += 1
        while i < n:
            nxt = body_lines[i].strip()
            if (not nxt or nxt.startswith("|") or nxt.startswith(">")
                or re.match(r"^[A-Z]\s*[｜|]\s*\d", nxt)
                or re.match(r"^[【\[].{2,20}[】\]]$", nxt)
                or re.match(r"^\d{1,2}[\.、\)）]\s", nxt)):
                break
            para.append(nxt); i += 1
        story.append(bd(" ".join(para)))

    doc.build(story)
    return len(text)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("用法: report_pdf.py <报告.txt> <输出.pdf> [封面副标题]")
    chars = build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    print(f"PDF_BUILT {chars}字 -> {sys.argv[2]}")
