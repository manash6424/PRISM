"""
PRISM — Professional PDF Report Generator v3
=============================================
Drop into backend/services/report_generator_pdf.py

Changes vs v2:
  Feature 1 — Logo on content-page top bar (tiny, right side of the accent bar)
  Feature 3 — Auto-detect logo aspect ratio; adjust white card size on cover
  Feature 4 — Fallback initials badge when no logo is uploaded
"""

import io, os, traceback
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker


def _get_store():
    try:
        from backend.upload_api import _upload_store
    except ModuleNotFoundError:
        from upload_api import _upload_store
    return _upload_store


router = APIRouter()

PAGE_W, PAGE_H = A4
MARGIN_L = 20*mm; MARGIN_R = 20*mm; MARGIN_T = 28*mm; MARGIN_B = 22*mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

DARK      = colors.HexColor("#0f1117")
OFF_WHITE = colors.HexColor("#f8f9fc")
TEXT_DARK = colors.HexColor("#111827")
TEXT_MID  = colors.HexColor("#374151")
TEXT_SOFT = colors.HexColor("#6b7280")
GREEN     = colors.HexColor("#22c55e")
RED_C     = colors.HexColor("#ef4444")
AMBER     = colors.HexColor("#f59e0b")
BLUE_C    = colors.HexColor("#3b82f6")
PURPLE    = colors.HexColor("#a855f7")
CYAN      = colors.HexColor("#06b6d4")
WHITE     = colors.white


class ReportRequest(BaseModel):
    agency_name:         Optional[str]  = "PRISM Agency"
    client_name:         Optional[str]  = "Client"
    report_title:        Optional[str]  = "Performance Report"
    prepared_by:         Optional[str]  = ""
    include_charts:      Optional[bool] = True
    accent_color:        Optional[str]  = "#e8455a"
    max_rows:            Optional[int]  = 80
    include_ai_insights: Optional[bool] = True
    logo_url:            Optional[str]  = ""


def hex_to_rl(h):
    h = h.lstrip("#")
    if len(h) == 3: h = "".join(c*2 for c in h)
    return colors.Color(int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255)

def lighten(c, f=0.82):
    return colors.Color(min(1,c.red+(1-c.red)*f), min(1,c.green+(1-c.green)*f), min(1,c.blue+(1-c.blue)*f))

def darken(c, f=0.25):
    return colors.Color(c.red*(1-f), c.green*(1-f), c.blue*(1-f))


# ── Feature 3 & 4 helpers ────────────────────────────────────────────────────

def _agency_initials(name: str) -> str:
    words = name.strip().split()
    if not words: return "AG"
    if len(words) == 1: return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def _fetch_logo_bytes(logo_url: str) -> bytes | None:
    """Download logo once and return raw bytes, or None on failure."""
    if not logo_url:
        return None
    try:
        import urllib.request
        with urllib.request.urlopen(logo_url, timeout=6) as resp:
            return resp.read()
    except Exception as e:
        print(f"[PDF LOGO FETCH] {e}")
        return None


def _logo_aspect(logo_bytes: bytes) -> float:
    """Return width/height ratio of the logo image. Falls back to 2.5."""
    if not logo_bytes:
        return 2.5
    try:
        from PIL import Image
        import io as _io
        with Image.open(_io.BytesIO(logo_bytes)) as im:
            w, h = im.size
            return w / h if h > 0 else 2.5
    except Exception:
        return 2.5


def _cover_card_size(aspect: float) -> tuple[float, float]:
    """
    Feature 3: Return (card_width_mm, card_height_mm) tuned to logo shape.
    Wide logo  → wide card; Square → squarish; Tall → narrower, taller.
    """
    if aspect > 1.8:
        return 36*mm, 16*mm       # wide logo
    elif aspect >= 0.8:
        return 22*mm, 20*mm       # square-ish logo
    else:
        return 18*mm, 24*mm       # tall/portrait logo


def make_styles(accent):
    S = {}
    S["cover_agency"]   = ParagraphStyle("cover_agency",   fontName="Helvetica-Bold", fontSize=10, textColor=colors.Color(1,1,1,0.7), spaceAfter=6)
    S["cover_title"]    = ParagraphStyle("cover_title",    fontName="Helvetica-Bold", fontSize=30, textColor=WHITE, spaceAfter=8, leading=36)
    S["cover_client"]   = ParagraphStyle("cover_client",   fontName="Helvetica",      fontSize=13, textColor=colors.Color(1,1,1,0.85), spaceAfter=4)
    S["cover_meta"]     = ParagraphStyle("cover_meta",     fontName="Helvetica",      fontSize=9,  textColor=colors.Color(1,1,1,0.6),  spaceAfter=3)
    S["section_heading"]= ParagraphStyle("section_heading",fontName="Helvetica-Bold", fontSize=12, textColor=accent, spaceBefore=12, spaceAfter=5)
    S["sub_heading"]    = ParagraphStyle("sub_heading",    fontName="Helvetica-Bold", fontSize=10, textColor=TEXT_DARK, spaceBefore=8, spaceAfter=4)
    S["body"]           = ParagraphStyle("body",           fontName="Helvetica",      fontSize=9,  textColor=TEXT_MID, leading=15, spaceAfter=4)
    S["body_small"]     = ParagraphStyle("body_small",     fontName="Helvetica",      fontSize=8,  textColor=TEXT_SOFT, leading=13, spaceAfter=3)
    S["kpi_label"]      = ParagraphStyle("kpi_label",      fontName="Helvetica",      fontSize=7.5,textColor=TEXT_SOFT, alignment=TA_CENTER, spaceAfter=3)
    S["table_header"]   = ParagraphStyle("table_header",   fontName="Helvetica-Bold", fontSize=7.5,textColor=WHITE, alignment=TA_LEFT)
    S["table_cell"]     = ParagraphStyle("table_cell",     fontName="Helvetica",      fontSize=8,  textColor=TEXT_DARK, alignment=TA_LEFT, leading=11)
    S["table_cell_c"]   = ParagraphStyle("table_cell_c",   fontName="Helvetica",      fontSize=8,  textColor=TEXT_DARK, alignment=TA_CENTER, leading=11)
    S["toc_item"]       = ParagraphStyle("toc_item",       fontName="Helvetica",      fontSize=10, textColor=TEXT_MID, leading=20, leftIndent=8)
    S["page_title"]     = ParagraphStyle("page_title",     fontName="Helvetica-Bold", fontSize=18, textColor=TEXT_DARK, spaceAfter=4)
    S["insight_title"]  = ParagraphStyle("insight_title",  fontName="Helvetica-Bold", fontSize=9.5,textColor=TEXT_DARK, leading=14)
    S["insight_detail"] = ParagraphStyle("insight_detail", fontName="Helvetica",      fontSize=8.5,textColor=TEXT_MID, leading=14)
    S["insight_num"]    = ParagraphStyle("insight_num",    fontName="Helvetica-Bold", fontSize=9,  textColor=accent, alignment=TA_CENTER)
    S["footer"]         = ParagraphStyle("footer",         fontName="Helvetica",      fontSize=7,  textColor=TEXT_SOFT, alignment=TA_CENTER)
    return S


# ── Page decorators ──────────────────────────────────────────────────────────

class CoverDeco:
    """
    Cover page background + logo/initials badge top-right.
    Feature 3: card sized to logo aspect ratio.
    Feature 4: initials badge fallback.
    """
    def __init__(self, accent, agency, client, title, logo_bytes=None, aspect=2.5):
        self.accent = accent
        self.agency = agency
        self.client = client
        self.title  = title
        self.logo_bytes = logo_bytes
        self.aspect = aspect

    def __call__(self, canv, doc):
        canv.saveState()
        w, h = PAGE_W, PAGE_H

        # Dark background + accent band
        canv.setFillColor(DARK); canv.rect(0, 0, w, h, fill=1, stroke=0)
        canv.setFillColor(self.accent); canv.rect(0, h*0.38, w, h*0.62, fill=1, stroke=0)
        canv.setFillColor(darken(self.accent, 0.15))
        p = canv.beginPath(); p.moveTo(0, h*0.38); p.lineTo(w, h*0.46); p.lineTo(w, h*0.38); p.close()
        canv.drawPath(p, fill=1, stroke=0)
        canv.setStrokeColor(colors.Color(1,1,1,0.06)); canv.setLineWidth(0.5)
        for x in range(0, int(w)+1, int(18*mm)): canv.line(x, h*0.38, x, h)
        for y in range(int(h*0.38), int(h)+1, int(14*mm)): canv.line(0, y, w, y)

        # Bottom decorations
        canv.setFillColor(colors.Color(1,1,1,0.04)); canv.rect(MARGIN_L, MARGIN_B, 60*mm, 12*mm, fill=1, stroke=0)
        canv.setFont("Helvetica-Bold", 9); canv.setFillColor(colors.Color(1,1,1,0.5))
        canv.drawString(MARGIN_L+4*mm, MARGIN_B+4*mm, "POWERED BY PRISM")
        canv.setFont("Helvetica", 8); canv.setFillColor(colors.Color(1,1,1,0.4))
        canv.drawRightString(w-MARGIN_R, MARGIN_B+4*mm, datetime.now().strftime("%d %B %Y"))

        # ── Logo or initials badge — top-right corner ──
        card_w, card_h = _cover_card_size(self.aspect)
        logo_x = w - MARGIN_R - card_w - 4*mm
        logo_y = h - MARGIN_T - card_h + 2*mm

        if self.logo_bytes:
            try:
                from reportlab.lib.utils import ImageReader
                img_reader = ImageReader(io.BytesIO(self.logo_bytes))
                # White card behind logo
                canv.setFillColor(colors.Color(1,1,1,0.95))
                canv.roundRect(logo_x - 3*mm, logo_y - 3*mm,
                               card_w + 6*mm, card_h + 6*mm,
                               2.5*mm, fill=1, stroke=0)
                canv.drawImage(img_reader, logo_x, logo_y,
                               width=card_w, height=card_h,
                               preserveAspectRatio=True, mask='auto')
            except Exception as e:
                print(f"[PDF COVER LOGO] {e}")
                self._draw_initials(canv, logo_x, logo_y, card_w, card_h)
        else:
            # Feature 4: initials badge
            self._draw_initials(canv, logo_x, logo_y, card_w, card_h)

        canv.restoreState()

    def _draw_initials(self, canv, x, y, w, h):
        initials = _agency_initials(self.agency)
        canv.setFillColor(self.accent)
        canv.roundRect(x, y, w, h, 4*mm, fill=1, stroke=0)
        canv.setFillColor(WHITE)
        font_size = min(w, h) * 0.38
        canv.setFont("Helvetica-Bold", font_size)
        canv.drawCentredString(x + w/2, y + h/2 - font_size*0.35, initials)


class ContentDeco:
    """
    Inner-page header + footer.
    Feature 1: tiny logo (or initials) in the top-right of the accent bar.
    """
    def __init__(self, accent, agency, client, title, logo_bytes=None, aspect=2.5):
        self.accent = accent
        self.agency = agency
        self.client = client
        self.title  = title
        self.logo_bytes = logo_bytes
        self.aspect = aspect

    def __call__(self, canv, doc):
        canv.saveState()
        w, h = PAGE_W, PAGE_H

        # Accent top bar (8mm tall)
        canv.setFillColor(self.accent); canv.rect(0, h-8*mm, w, 8*mm, fill=1, stroke=0)

        # Agency name — left side of bar
        canv.setFont("Helvetica-Bold", 7.5); canv.setFillColor(WHITE)
        canv.drawString(MARGIN_L, h-5.5*mm, self.agency.upper())

        # ── Feature 1: Logo or initials — right side of top bar ──
        bar_top    = h - 8*mm
        bar_height = 8*mm

        if self.logo_bytes:
            try:
                from reportlab.lib.utils import ImageReader

                # Aspect-aware logo size inside the bar
                if self.aspect > 1.8:
                    logo_w = 22*mm; logo_h = 5.5*mm
                elif self.aspect >= 0.8:
                    logo_w = 7*mm;  logo_h = 5.5*mm
                else:
                    logo_w = 5*mm;  logo_h = 6*mm

                logo_x = w - MARGIN_R - logo_w - 2*mm
                logo_y = bar_top + (bar_height - logo_h) / 2

                # Small white pill behind logo
                pad = 1.5*mm
                canv.setFillColor(colors.Color(1,1,1,0.92))
                canv.roundRect(logo_x - pad, logo_y - pad,
                               logo_w + 2*pad, logo_h + 2*pad,
                               1.5*mm, fill=1, stroke=0)

                img_reader = ImageReader(io.BytesIO(self.logo_bytes))
                canv.drawImage(img_reader, logo_x, logo_y,
                               width=logo_w, height=logo_h,
                               preserveAspectRatio=True, mask='auto')

            except Exception as e:
                print(f"[PDF CONTENT LOGO] {e}")
                self._draw_initials_bar(canv, w, bar_top, bar_height)
        else:
            # Feature 4: tiny initials badge in bar
            self._draw_initials_bar(canv, w, bar_top, bar_height)

        # "Prepared for: Client" label — but only if logo is wide or absent
        # (skip the label when a wide logo is already there to avoid overlap)
        if not self.logo_bytes or self.aspect <= 1.8:
            label_x = w - MARGIN_R - (25*mm if self.logo_bytes else 0) - 2*mm
            canv.setFont("Helvetica", 7.5); canv.setFillColor(WHITE)
            canv.drawRightString(label_x, h-5.5*mm, f"Prepared for: {self.client}")
        else:
            # Wide logo occupies that space — write client name left of the logo
            logo_w = 22*mm
            label_x = w - MARGIN_R - logo_w - 6*mm
            canv.setFont("Helvetica", 7.5); canv.setFillColor(WHITE)
            canv.drawRightString(label_x, h-5.5*mm, f"Prepared for: {self.client}")

        # Thin rule below header
        canv.setStrokeColor(colors.HexColor("#e5e7eb")); canv.setLineWidth(0.4)
        canv.line(MARGIN_L, h-11*mm, w-MARGIN_R, h-11*mm)

        # Footer
        canv.setFont("Helvetica", 7); canv.setFillColor(TEXT_SOFT)
        canv.drawCentredString(w/2, MARGIN_B-8*mm,
            f"{self.title}  |  {datetime.now().strftime('%d %b %Y')}  |  Page {doc.page}")
        canv.line(MARGIN_L, MARGIN_B-4*mm, w-MARGIN_R, MARGIN_B-4*mm)

        # Left accent stripe
        canv.setFillColor(lighten(self.accent, 0.88))
        canv.rect(0, MARGIN_B-4*mm, 3*mm, h-MARGIN_T-MARGIN_B+4*mm, fill=1, stroke=0)

        canv.restoreState()

    def _draw_initials_bar(self, canv, w, bar_top, bar_height):
        """Feature 4: draw tiny initials badge inside the top accent bar."""
        initials = _agency_initials(self.agency)
        badge_w  = 10*mm
        badge_h  = bar_height * 0.65
        badge_x  = w - MARGIN_R - badge_w - 2*mm
        badge_y  = bar_top + (bar_height - badge_h) / 2
        canv.setFillColor(colors.Color(0, 0, 0, 0.25))
        canv.roundRect(badge_x, badge_y, badge_w, badge_h, 1.5*mm, fill=1, stroke=0)
        canv.setFillColor(WHITE)
        font_sz = badge_h * 0.50
        canv.setFont("Helvetica-Bold", font_sz)
        canv.drawCentredString(badge_x + badge_w/2, badge_y + badge_h/2 - font_sz*0.35, initials)


# ── KPI detection (unchanged) ────────────────────────────────────────────────

def detect_kpis(df):
    cols = list(df.columns)
    def find(keys):
        for k in keys:
            for c in cols:
                if k in c.lower(): return c
        return None
    spend_col = find(["spend","cost","amount","budget","expense"])
    imp_col   = find(["impression","impr","reach"])
    click_col = find(["click"])
    conv_col  = find(["conversion","result","purchase","lead","order"])
    rev_col   = find(["revenue","value","sales","income","earning"])
    camp_col  = find(["campaign","ad_set","adset","ad_name"])
    date_col  = find(["date","day","week","month"])
    chan_col  = find(["channel","platform","source","medium","network"])
    def s(c):
        return float(pd.to_numeric(df[c],errors="coerce").fillna(0).sum()) if c else 0.0
    ts=s(spend_col); ti=s(imp_col); tc=s(click_col); tcv=s(conv_col); tr=s(rev_col)
    roas = round(tr/ts,2)      if ts>0 else 0
    ctr  = round(tc/ti*100,2)  if ti>0 else 0
    cpc  = round(ts/tc,2)      if tc>0 else 0
    cpa  = round(ts/tcv,2)     if tcv>0 else 0
    cvr  = round(tcv/tc*100,2) if tc>0 else 0
    campaigns = []
    if camp_col:
        agg = {k:v for k,v in {"spend":spend_col,"impressions":imp_col,"clicks":click_col,"conversions":conv_col,"revenue":rev_col}.items() if v}
        for v in agg.values(): df[v] = pd.to_numeric(df[v],errors="coerce").fillna(0)
        grp = df.groupby(camp_col)[list(agg.values())].sum().reset_index()
        grp.columns = [camp_col] + list(agg.keys())
        for _, row in grp.iterrows():
            sp=float(row.get("spend",0)); rv=float(row.get("revenue",0))
            cl=float(row.get("clicks",0)); im=float(row.get("impressions",0)); cv=float(row.get("conversions",0))
            campaigns.append({"name":str(row[camp_col]),"spend":round(sp,2),"revenue":round(rv,2),
                "clicks":int(cl),"impressions":int(im),"conversions":int(cv),
                "roas":round(rv/sp,2) if sp>0 else 0,"ctr":round(cl/im*100,2) if im>0 else 0,
                "cpc":round(sp/cl,2) if cl>0 else 0})
        campaigns.sort(key=lambda x:x["spend"], reverse=True)
    daily = []
    if date_col and spend_col:
        tmp = df.copy(); tmp["_d"] = pd.to_datetime(tmp[date_col], errors="coerce")
        ds = tmp.groupby("_d")[spend_col].sum().reset_index().dropna(subset=["_d"]).sort_values("_d")
        daily = [{"date":str(r["_d"])[:10],"spend":round(float(r[spend_col]),2)} for _,r in ds.iterrows()]
    is_mkt = bool(spend_col or imp_col or click_col or rev_col)
    return {"is_marketing":is_mkt,"kpis":{"total_spend":ts,"total_impressions":int(ti),"total_clicks":int(tc),
        "total_conversions":int(tcv),"total_revenue":tr,"roas":roas,"ctr":ctr,"cpc":cpc,"cpa":cpa,"cvr":cvr},
        "campaigns":campaigns[:15],"daily_spend":daily,
        "detected":{"spend":spend_col,"impressions":imp_col,"clicks":click_col,
                    "revenue":rev_col,"campaign":camp_col,"date":date_col}}


def get_ai_insights(kpi_info, files):
    try:
        from groq import Groq
        import json
        key = os.environ.get("GROQ_API_KEY","")
        if not key: raise ValueError("no key")
        kpis  = kpi_info["kpis"]; camps = kpi_info["campaigns"][:5]
        prompt = f"""You are a senior digital marketing analyst at an Indian agency.
Analyze this campaign data and write 5 sharp, actionable insights for a client PDF report.
KPIs: Spend Rs.{kpis['total_spend']:,.0f}, Revenue Rs.{kpis['total_revenue']:,.0f}, ROAS {kpis['roas']}x, CTR {kpis['ctr']}%, CPC Rs.{kpis['cpc']}, CPA Rs.{kpis['cpa']}, Conversions {kpis['total_conversions']}, Impressions {kpis['total_impressions']:,}
Top Campaigns: {[c['name']+' ROAS:'+str(c['roas'])+'x' for c in camps]}
Write exactly 5 insights as JSON array with keys "title" and "detail". 1-sentence title + 1-2 sentence detail. Use Rs. for amounts. Be specific with numbers. Return ONLY valid JSON array."""
        client = Groq(api_key=key)
        resp = client.chat.completions.create(model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}], max_tokens=600, temperature=0.3)
        text = resp.choices[0].message.content.strip().replace("```json","").replace("```","").strip()
        return json.loads(text)[:5]
    except Exception:
        kpis = kpi_info["kpis"]; camps = kpi_info["campaigns"]
        ins = []
        roas = kpis.get("roas",0)
        if roas > 0:
            status = "strong" if roas>=3 else "below target" if roas<2 else "moderate"
            ins.append({"title":f"Overall ROAS is {roas}x — {status} performance",
                "detail":f"For every Rs.1 spent, campaigns generated Rs.{roas} in revenue. "+
                ("This is a healthy return. Consider scaling budgets." if roas>=3 else "Industry benchmark is 3-4x. Focus on optimizing underperforming campaigns.")})
        ctr = kpis.get("ctr",0)
        if ctr > 0:
            ins.append({"title":f"CTR of {ctr}% — {'above' if ctr>2 else 'below'} industry average",
                "detail":f"Average CTR across all campaigns is {ctr}%. "+("Strong creative engagement across placements." if ctr>2 else "Consider A/B testing new creatives and headlines to improve engagement rates.")})
        if camps:
            best = max(camps, key=lambda x: x["roas"])
            ins.append({"title":f"'{best['name']}' is the top performer",
                "detail":f"With ROAS of {best['roas']}x and Rs.{best['spend']:,.0f} spend, this campaign delivers best returns. Recommend increasing budget allocation by 20-30%."})
            if len(camps) > 1:
                worst = min(camps, key=lambda x: x["roas"])
                if worst["name"] != best["name"]:
                    ins.append({"title":f"'{worst['name']}' needs urgent review",
                        "detail":f"ROAS of {worst['roas']}x is the lowest. Review targeting, creatives, and landing page. Consider pausing if no improvement within 7 days."})
        cpa = kpis.get("cpa",0)
        if cpa > 0:
            ins.append({"title":f"Cost per Acquisition at Rs.{cpa:,.0f}",
                "detail":f"Each conversion costs Rs.{cpa:,.0f}. Compare against average order/client value to assess true profitability. Aim to reduce CPA by 15-20% through better audience targeting."})
        return ins[:5]


def fmt_n(n, prefix=""):
    if n == 0: return "0"
    if abs(n) >= 1_000_000: return f"{prefix}{n/1_000_000:.2f}M"
    if abs(n) >= 1_000: return f"{prefix}{n/1_000:.1f}K"
    return f"{prefix}{n:,.0f}" if isinstance(n,(int,float)) and n==int(n) else f"{prefix}{n:,.2f}"

def fmt_inr(n): return fmt_n(n, "Rs.")
def pct(n): return f"{n}%"
def cell(text, style): return Paragraph(str(text), style)

def colored_cell(text, base_style, val, good, bad):
    if isinstance(val,(int,float)):
        color = GREEN if val>=good else RED_C if val<=bad else AMBER
        hex_c = f"#{int(color.red*255):02x}{int(color.green*255):02x}{int(color.blue*255):02x}"
        s = ParagraphStyle(base_style.name+"x", parent=base_style, textColor=color, fontName="Helvetica-Bold")
        return Paragraph(str(text), s)
    return Paragraph(str(text), base_style)


# ── Story builders (unchanged except signatures take logo_bytes) ─────────────

def build_cover(story, req, accent, S):
    story.append(Spacer(1, 48*mm))
    story.append(Paragraph(req.agency_name.upper(), S["cover_agency"]))
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph(req.report_title, S["cover_title"]))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(f"Prepared for: <b>{req.client_name}</b>", S["cover_client"]))
    story.append(Spacer(1, 10*mm))
    story.append(Paragraph(f"Report Date: {datetime.now().strftime('%d %B %Y')}", S["cover_meta"]))
    if req.prepared_by:
        story.append(Paragraph(f"Prepared by: {req.prepared_by}", S["cover_meta"]))
    story.append(NextPageTemplate("Content"))
    story.append(PageBreak())


def build_toc(story, S, accent, sections):
    story.append(Paragraph("Contents", S["page_title"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1.5, color=accent))
    story.append(Spacer(1, 6*mm))
    for i, sec in enumerate(sections, 1):
        t = Table([[Paragraph(f"{i}.", ParagraphStyle("n",fontName="Helvetica-Bold",fontSize=10,textColor=accent)),
                    Paragraph(sec, S["toc_item"])]], colWidths=[10*mm, CONTENT_W-10*mm])
        t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
        story.append(t)
        story.append(HRFlowable(width=CONTENT_W, thickness=0.3, color=colors.HexColor("#e5e7eb"), dash=(1,4)))
    story.append(PageBreak())


def build_executive_summary(story, S, accent, kpi_info, files, req):
    story.append(Paragraph("01 — Executive Summary", S["section_heading"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=accent))
    story.append(Spacer(1, 4*mm))
    kpis = kpi_info["kpis"]; date_str = datetime.now().strftime("%B %Y")
    ts=kpis.get("total_spend",0); tr=kpis.get("total_revenue",0); tcv=kpis.get("total_conversions",0); roas=kpis.get("roas",0)
    if kpi_info["is_marketing"] and ts > 0:
        txt = (f"This report covers campaign performance for <b>{req.client_name}</b> for {date_str}. "
               f"A total of <b>{fmt_inr(ts)}</b> was invested across {len(files)} data source(s), ")
        if tr > 0: txt += f"generating <b>{fmt_inr(tr)}</b> in revenue with a ROAS of <b>{roas}x</b>. "
        if tcv > 0: txt += f"The campaigns delivered <b>{fmt_n(tcv)}</b> conversions. "
        txt += "Detailed performance metrics and actionable recommendations are in the sections below."
    else:
        total = sum(f["row_count"] for f in files)
        txt = (f"This report presents data analysis for <b>{req.client_name}</b> for {date_str}. "
               f"The analysis covers <b>{total:,} records</b> across {len(files)} data file(s). Key findings follow.")
    story.append(Paragraph(txt, S["body"]))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph("Data Sources", S["sub_heading"]))
    rows = [[cell("File Name",S["table_header"]),cell("Rows",S["table_header"]),cell("Columns",S["table_header"])]]
    for f in files:
        rows.append([cell(f["filename"],S["table_cell"]),cell(f"{f['row_count']:,}",S["table_cell_c"]),cell(str(len(f["columns"])),S["table_cell_c"])])
    ft = Table(rows, colWidths=[CONTENT_W*0.65, CONTENT_W*0.175, CONTENT_W*0.175])
    ft.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),accent),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),8.5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[OFF_WHITE,WHITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e5e7eb")),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1),8),("ALIGN",(1,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
    story.append(ft)
    story.append(Spacer(1, 6*mm))


def build_kpi_section(story, S, accent, kpis):
    story.append(Paragraph("02 — Key Performance Indicators", S["section_heading"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=accent))
    story.append(Spacer(1, 4*mm))
    items = [("Total Spend",fmt_inr(kpis["total_spend"]),"#e8455a"),
             ("Total Revenue",fmt_inr(kpis["total_revenue"]),"#22c55e"),
             ("ROAS",f"{kpis['roas']}x","#f59e0b"),
             ("CTR",pct(kpis["ctr"]),"#3b82f6"),
             ("Total Clicks",fmt_n(kpis["total_clicks"]),"#06b6d4"),
             ("CPC",fmt_inr(kpis["cpc"]),"#a855f7"),
             ("Conversions",fmt_n(kpis["total_conversions"]),"#22c55e"),
             ("CPA",fmt_inr(kpis["cpa"]),"#f59e0b")]
    card_w = CONTENT_W/4 - 1.5*mm
    def make_card(label, value, col_hex):
        ac = hex_to_rl(col_hex)
        cd = [[Paragraph(label, S["kpi_label"])],
              [Paragraph(f'<font color="{col_hex}"><b>{value}</b></font>',
                  ParagraphStyle("kv",fontName="Helvetica-Bold",fontSize=18,alignment=TA_CENTER,leading=22))]]
        t = Table(cd, colWidths=[card_w])
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),OFF_WHITE),("BOX",(0,0),(-1,-1),1.5,ac),
            ("LINEABOVE",(0,0),(-1,0),3,ac),("TOPPADDING",(0,0),(-1,-1),8),
            ("BOTTOMPADDING",(0,0),(-1,-1),10),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]))
        return t
    for rs in range(0, 8, 4):
        row = [make_card(items[i][0],items[i][1],items[i][2]) for i in range(rs, min(rs+4,len(items)))]
        while len(row) < 4: row.append("")
        rt = Table([row], colWidths=[card_w+1.5*mm]*4)
        rt.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),1),
            ("RIGHTPADDING",(0,0),(-1,-1),1),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
        story.append(rt); story.append(Spacer(1, 2*mm))
    story.append(Spacer(1, 4*mm))


def build_roas_chart(campaigns, accent):
    top = campaigns[:6]
    if not top: return None
    d = Drawing(CONTENT_W/2-5*mm, 120)
    bc = VerticalBarChart()
    bc.x=38; bc.y=25; bc.width=CONTENT_W/2-55; bc.height=82
    bc.data = [[c["roas"] for c in top]]
    bc.bars[0].fillColor = accent
    bc.categoryAxis.categoryNames = [c["name"][:12] for c in top]
    bc.categoryAxis.labels.angle=30; bc.categoryAxis.labels.fontSize=6; bc.categoryAxis.labels.dy=-8
    bc.valueAxis.valueMin=0; bc.valueAxis.labels.fontSize=6; bc.groupSpacing=8
    d.add(bc)
    d.add(String(d.width/2,112,"ROAS by Campaign",fontSize=8,fontName="Helvetica-Bold",
                 fillColor=colors.HexColor("#374151"),textAnchor="middle"))
    return d


def build_spend_chart(daily, accent):
    if not daily: return None
    d = Drawing(CONTENT_W/2-5*mm, 120)
    lp = LinePlot()
    lp.x=38; lp.y=25; lp.width=CONTENT_W/2-55; lp.height=82
    lp.data = [[(i, r["spend"]) for i, r in enumerate(daily)]]
    lp.lines[0].strokeColor=accent; lp.lines[0].strokeWidth=1.8
    lp.lines[0].symbol=makeMarker("FilledCircle"); lp.lines[0].symbol.size=3; lp.lines[0].symbol.fillColor=accent
    lp.xValueAxis.valueMin=0; lp.xValueAxis.valueMax=max(len(daily)-1,1)
    lp.xValueAxis.labels.fontSize=6; lp.yValueAxis.valueMin=0; lp.yValueAxis.labels.fontSize=6
    d.add(lp)
    step = max(1, len(daily)//5)
    for i in range(0, len(daily), step):
        xp = lp.x + (i/max(len(daily)-1,1))*lp.width
        d.add(String(xp, lp.y-14, daily[i]["date"][5:], fontSize=5.5, fillColor=colors.HexColor("#9ca3af"), textAnchor="middle"))
    d.add(String(d.width/2,112,"Daily Spend Trend",fontSize=8,fontName="Helvetica-Bold",
                 fillColor=colors.HexColor("#374151"),textAnchor="middle"))
    return d


def build_charts_section(story, S, accent, kpi_info):
    story.append(Paragraph("03 — Performance Charts", S["section_heading"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=accent))
    story.append(Spacer(1, 4*mm))
    rd = build_roas_chart(kpi_info["campaigns"], accent)
    sd = build_spend_chart(kpi_info["daily_spend"], accent)
    if not rd and not sd:
        story.append(Paragraph("Insufficient data for charts.", S["body_small"])); return
    cw = CONTENT_W/2 - 2*mm
    ct = Table([[rd or "", sd or ""]], colWidths=[cw+2*mm, cw])
    ct.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("BACKGROUND",(0,0),(-1,-1),OFF_WHITE),
        ("BOX",(0,0),(0,0),0.5,colors.HexColor("#e5e7eb")),("BOX",(1,0),(1,0),0.5,colors.HexColor("#e5e7eb")),
        ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]))
    story.append(ct); story.append(Spacer(1, 6*mm))


def build_campaign_section(story, S, accent, campaigns):
    story.append(Paragraph("04 — Campaign Breakdown", S["section_heading"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=accent))
    story.append(Spacer(1, 3*mm))
    if not campaigns:
        story.append(Paragraph("No campaign data detected.", S["body_small"])); return
    headers = ["Campaign","Spend","Revenue","ROAS","CTR","Clicks","CPC","Conv."]
    header_row = [cell(h, S["table_header"]) for h in headers]
    col_w = [CONTENT_W*f for f in [0.26,0.11,0.11,0.09,0.09,0.10,0.10,0.14]]
    rows = [header_row]
    for c in campaigns:
        rows.append([cell(c["name"][:30],S["table_cell"]),cell(fmt_inr(c["spend"]),S["table_cell_c"]),
            cell(fmt_inr(c["revenue"]),S["table_cell_c"]),
            colored_cell(f"{c['roas']}x",S["table_cell_c"],c["roas"],3.0,1.5),
            colored_cell(f"{c['ctr']}%",S["table_cell_c"],c["ctr"],2.0,0.5),
            cell(fmt_n(c["clicks"]),S["table_cell_c"]),cell(fmt_inr(c["cpc"]),S["table_cell_c"]),
            cell(fmt_n(c["conversions"]),S["table_cell_c"])])
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),accent),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[OFF_WHITE,WHITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e5e7eb")),
        ("ALIGN",(1,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6)]))
    story.append(t); story.append(Spacer(1, 2*mm))
    legend = Table([[Paragraph('<font color="#22c55e">&#9632;</font> Good (ROAS &gt;=3x, CTR &gt;=2%)',S["body_small"]),
                     Paragraph('<font color="#f59e0b">&#9632;</font> Average',S["body_small"]),
                     Paragraph('<font color="#ef4444">&#9632;</font> Needs Attention',S["body_small"])]],
                   colWidths=[CONTENT_W/3]*3)
    legend.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
    story.append(legend); story.append(Spacer(1, 6*mm))


def build_insights_section(story, S, accent, kpi_info, files):
    story.append(Paragraph("05 — AI-Powered Insights & Recommendations", S["section_heading"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=accent))
    story.append(Spacer(1, 4*mm))
    insights = get_ai_insights(kpi_info, files)
    icon_colors = [accent, GREEN, AMBER, BLUE_C, PURPLE]
    for i, ins in enumerate(insights):
        color = icon_colors[i % len(icon_colors)]
        hex_c = f"#{int(color.red*255):02x}{int(color.green*255):02x}{int(color.blue*255):02x}"
        num_s = ParagraphStyle("ns",fontName="Helvetica-Bold",fontSize=9,textColor=color,alignment=TA_CENTER)
        row = Table([[Paragraph(f'<font color="{hex_c}">0{i+1}</font>',num_s),
                      Paragraph(ins.get("title",""),S["insight_title"])],
                     ["", Paragraph(ins.get("detail",""),S["insight_detail"])]],
                    colWidths=[10*mm, CONTENT_W-10*mm])
        row.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),2),
            ("BOTTOMPADDING",(0,0),(-1,-1),2),("SPAN",(0,0),(0,1))]))
        card = Table([[row]], colWidths=[CONTENT_W])
        card.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),OFF_WHITE),
            ("BOX",(0,0),(-1,-1),0.5,colors.HexColor("#e5e7eb")),
            ("LINEBEFORE",(0,0),(0,-1),3,color),
            ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
            ("LEFTPADDING",(0,0),(-1,-1),10),("RIGHTPADDING",(0,0),(-1,-1),10)]))
        story.append(card); story.append(Spacer(1, 3*mm))
    story.append(Spacer(1, 4*mm))


def build_data_section(story, S, accent, df, max_rows, sec_num):
    story.append(Paragraph(f"0{sec_num} — Data Preview", S["section_heading"]))
    story.append(HRFlowable(width=CONTENT_W, thickness=1, color=accent))
    story.append(Spacer(1, 1*mm))
    story.append(Paragraph(f"Showing first {min(max_rows,len(df))} of {len(df):,} rows  |  {len(df.columns)} columns",S["body_small"]))
    story.append(Spacer(1, 3*mm))
    cols = list(df.columns)[:10]; df_d = df[cols].head(max_rows).fillna("")
    col_w = [CONTENT_W/len(cols)]*len(cols)
    rows = [[cell(str(c)[:16], S["table_header"]) for c in cols]]
    for _, row in df_d.iterrows():
        rows.append([cell(str(row[c])[:30], S["table_cell"]) for c in cols])
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),accent),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[OFF_WHITE,WHITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#e5e7eb")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),4),
        ("BOTTOMPADDING",(0,0),(-1,-1),4),("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5)]))
    story.append(t); story.append(Spacer(1, 6*mm))


def build_closing(story, S, accent, req):
    story.append(PageBreak()); story.append(Spacer(1, 20*mm))
    story.append(HRFlowable(width=CONTENT_W, thickness=2, color=accent))
    story.append(Spacer(1, 8*mm))
    story.append(Paragraph("Thank you for your business.",
        ParagraphStyle("thanks",fontName="Helvetica-Bold",fontSize=16,textColor=TEXT_DARK,alignment=TA_CENTER)))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        f"Prepared by <b>{req.agency_name}</b> for <b>{req.client_name}</b>.<br/>"
        f"Generated by PRISM on {datetime.now().strftime('%d %B %Y at %H:%M')}.<br/>"
        "All data sourced directly from uploaded files without modification.",
        ParagraphStyle("cb",fontName="Helvetica",fontSize=9,textColor=TEXT_SOFT,alignment=TA_CENTER,leading=16)))
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=lighten(accent)))


# ── Main generate function ────────────────────────────────────────────────────

def generate_pdf(session_store, req):
    accent    = hex_to_rl(req.accent_color or "#e8455a")
    S         = make_styles(accent)
    df        = session_store["merged_df"]
    files     = session_store["files"]
    kpi_info  = detect_kpis(df)
    logo_url  = getattr(req, 'logo_url', '') or ''

    # ── Fetch logo once; detect aspect ──────────────────────────────────
    logo_bytes = _fetch_logo_bytes(logo_url)
    aspect     = _logo_aspect(logo_bytes) if logo_bytes else 2.5
    print(f"[PDF] logo fetched={logo_bytes is not None}, aspect={aspect:.2f}")

    buf = io.BytesIO()

    cover_deco   = CoverDeco(accent, req.agency_name, req.client_name, req.report_title, logo_bytes, aspect)
    content_deco = ContentDeco(accent, req.agency_name, req.client_name, req.report_title, logo_bytes, aspect)

    cf = Frame(MARGIN_L, MARGIN_B, CONTENT_W, PAGE_H-MARGIN_T-MARGIN_B,
               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    nf = Frame(MARGIN_L, MARGIN_B, CONTENT_W, PAGE_H-MARGIN_T-MARGIN_B-4*mm,
               leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    doc = BaseDocTemplate(buf, pagesize=A4,
        pageTemplates=[
            PageTemplate(id="Cover",   frames=[cf], onPage=cover_deco),
            PageTemplate(id="Content", frames=[nf], onPage=content_deco),
        ],
        leftMargin=MARGIN_L, rightMargin=MARGIN_R, topMargin=MARGIN_T, bottomMargin=MARGIN_B)

    story = []
    sections = ["Executive Summary"]
    if kpi_info["is_marketing"]:
        sections += ["Key Performance Indicators","Performance Charts","Campaign Breakdown","AI Insights & Recommendations"]
    sections.append("Data Preview")

    story.append(NextPageTemplate("Cover"))
    build_cover(story, req, accent, S)
    build_toc(story, S, accent, sections)
    build_executive_summary(story, S, accent, kpi_info, files, req)
    if kpi_info["is_marketing"]:
        story.append(PageBreak())
        build_kpi_section(story, S, accent, kpi_info["kpis"])
        if req.include_charts:
            story.append(PageBreak())
            build_charts_section(story, S, accent, kpi_info)
        story.append(PageBreak())
        build_campaign_section(story, S, accent, kpi_info["campaigns"])
        if req.include_ai_insights:
            story.append(PageBreak())
            build_insights_section(story, S, accent, kpi_info, files)
    story.append(PageBreak())
    build_data_section(story, S, accent, df, req.max_rows, len(sections))
    build_closing(story, S, accent, req)

    doc.build(story)
    return buf.getvalue()


# ── FastAPI routes (unchanged) ────────────────────────────────────────────────

@router.post("/report/pdf/{session_id}")
async def generate_pdf_report(session_id: str, req: ReportRequest = None):
    if req is None: req = ReportRequest()
    print(f"[PDF] logo_url='{req.logo_url}'")
    store = _get_store()
    if session_id not in store: raise HTTPException(status_code=404, detail="Session not found")
    session = store[session_id]
    if session.get("merged_df") is None: raise HTTPException(status_code=400, detail="No data in session")
    try:
        pdf_bytes = generate_pdf(session, req)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="PDF generation failed — check server logs")
    safe = (req.client_name or "report").replace(" ", "_")
    filename = f"PRISM_{safe}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/report/pdf/{session_id}/preview")
async def pdf_preview(session_id: str):
    store = _get_store()
    if session_id not in store: raise HTTPException(status_code=404, detail="Session not found")
    session = store[session_id]; df = session.get("merged_df"); files = session.get("files",[])
    if df is None: raise HTTPException(status_code=400, detail="No data in session")
    kpi_info = detect_kpis(df)
    sections = ["Executive Summary"]
    if kpi_info["is_marketing"]:
        sections += ["Key Performance Indicators","Performance Charts","Campaign Breakdown","AI Insights & Recommendations"]
    sections.append("Data Preview")
    return {"success":True,"file_count":len(files),"total_rows":len(df),"column_count":len(df.columns),
        "filenames":[f["filename"] for f in files],"is_marketing":kpi_info["is_marketing"],
        "detected_cols":kpi_info["detected"],"campaign_count":len(kpi_info["campaigns"]),
        "has_daily_spend":len(kpi_info["daily_spend"])>0,"sections":sections}