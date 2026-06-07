"""
PRISM — KPI Report Generator
Generates a rich, white-label Excel report from marketing KPI data.
Drop this file into: backend/services/kpi_report_generator.py
"""

import io
from datetime import datetime
from typing import Any

try:
    import xlsxwriter
except ImportError:
    raise ImportError("Run: pip install xlsxwriter")


# ──────────────────────────────────────────────
# COLOUR PALETTE  (edit brand colours here)
# ──────────────────────────────────────────────
PRIMARY      = "#1a1f3a"
ACCENT       = "#4f8ef7"
ACCENT_LIGHT = "#dce9ff"
WHITE        = "#ffffff"
LIGHT_GREY   = "#f4f6fb"
MID_GREY     = "#e0e4ef"
TEXT_DARK    = "#1a1f3a"
TEXT_MID     = "#5a6380"
GREEN        = "#22c55e"
RED          = "#ef4444"
AMBER        = "#f59e0b"


def _hex(colour: str) -> str:
    return colour.lstrip("#")


def generate_kpi_excel(
    kpi_data: dict[str, Any],
    campaign_rows: list[dict],
    daily_rows: list[dict],
    client_name: str = "Client",
    agency_name: str = "Your Agency",
    date_range: str = "",
) -> bytes:
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_numbers": True})

    def fmt(**kw):
        return wb.add_format(kw)

    cover_title = fmt(
        bold=True, font_size=28, font_color=_hex(WHITE),
        bg_color=_hex(PRIMARY), align="center", valign="vcenter",
        font_name="Calibri",
    )
    cover_sub = fmt(
        font_size=14, font_color=_hex(ACCENT_LIGHT),
        bg_color=_hex(PRIMARY), align="center", valign="vcenter",
        font_name="Calibri",
    )
    cover_meta = fmt(
        font_size=11, font_color=_hex(TEXT_MID),
        bg_color=_hex(LIGHT_GREY), align="center", valign="vcenter",
        font_name="Calibri",
    )
    kpi_label = fmt(
        bold=True, font_size=9, font_color=_hex(TEXT_MID),
        bg_color=_hex(LIGHT_GREY), align="center", valign="vcenter",
        font_name="Calibri", border=0,
    )
    kpi_value = fmt(
        bold=True, font_size=20, font_color=_hex(TEXT_DARK),
        bg_color=_hex(WHITE), align="center", valign="vcenter",
        font_name="Calibri",
        top=2, bottom=2, left=2, right=2,
        top_color=_hex(ACCENT), bottom_color=_hex(ACCENT),
        left_color=_hex(ACCENT), right_color=_hex(ACCENT),
    )
    kpi_value_good = fmt(
        bold=True, font_size=20, font_color=_hex(GREEN),
        bg_color=_hex(WHITE), align="center", valign="vcenter",
        font_name="Calibri",
        top=2, bottom=2, left=2, right=2,
        top_color=_hex(GREEN), bottom_color=_hex(GREEN),
        left_color=_hex(GREEN), right_color=_hex(GREEN),
    )
    tbl_header = fmt(
        bold=True, font_size=10, font_color=_hex(WHITE),
        bg_color=_hex(PRIMARY), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
        text_wrap=True,
    )
    tbl_row = fmt(
        font_size=10, font_color=_hex(TEXT_DARK),
        bg_color=_hex(WHITE), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
    )
    tbl_row_alt = fmt(
        font_size=10, font_color=_hex(TEXT_DARK),
        bg_color=_hex(LIGHT_GREY), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
    )
    tbl_currency = fmt(
        font_size=10, font_color=_hex(TEXT_DARK),
        bg_color=_hex(WHITE), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
        num_format="₹#,##0.00",
    )
    tbl_currency_alt = fmt(
        font_size=10, font_color=_hex(TEXT_DARK),
        bg_color=_hex(LIGHT_GREY), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
        num_format="₹#,##0.00",
    )
    tbl_pct = fmt(
        font_size=10, font_color=_hex(TEXT_DARK),
        bg_color=_hex(WHITE), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
        num_format="0.00%",
    )
    tbl_pct_alt = fmt(
        font_size=10, font_color=_hex(TEXT_DARK),
        bg_color=_hex(LIGHT_GREY), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
        num_format="0.00%",
    )
    section_head = fmt(
        bold=True, font_size=13, font_color=_hex(PRIMARY),
        bg_color=_hex(ACCENT_LIGHT), align="left", valign="vcenter",
        font_name="Calibri", left=4, left_color=_hex(ACCENT),
        bottom=1, bottom_color=_hex(ACCENT),
    )
    footer_fmt = fmt(
        italic=True, font_size=9, font_color=_hex(TEXT_MID),
        align="right", font_name="Calibri",
    )
    tbl_scale = fmt(
        bold=True, font_size=10, font_color=_hex(WHITE),
        bg_color=_hex(GREEN), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
    )
    tbl_pause = fmt(
        bold=True, font_size=10, font_color=_hex(WHITE),
        bg_color=_hex(RED), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
    )
    tbl_hold = fmt(
        bold=True, font_size=10, font_color=_hex(TEXT_DARK),
        bg_color=_hex(AMBER), align="center", valign="vcenter",
        font_name="Calibri", border=1, border_color=_hex(MID_GREY),
    )

    # ── SHEET 1: COVER ────────────────────────────────────────────────────
    cover = wb.add_worksheet("Cover")
    cover.hide_gridlines(2)
    cover.set_tab_color(_hex(PRIMARY))
    cover.set_column("A:J", 14)
    cover.set_zoom(85)
    for r in range(0, 20):
        cover.set_row(r, 15)

    navy_bg = fmt(bg_color=_hex(PRIMARY))
    for r in [0, 1, 4, 5, 6, 7]:
        cover.set_row(r, 28)
        cover.merge_range(r, 0, r, 9, "", navy_bg)

    cover.set_row(2, 60)
    cover.merge_range(2, 0, 2, 9, "PRISM  ·  Marketing KPI Report", cover_title)
    cover.set_row(3, 36)
    cover.merge_range(3, 0, 3, 9, f"{client_name}  ·  {date_range}", cover_sub)

    light_bg = fmt(bg_color=_hex(LIGHT_GREY))

    cover.set_row(8, 26)
    cover.merge_range(8, 0, 8, 9, f"Prepared by {agency_name}", cover_meta)
    cover.set_row(9, 26)
    cover.merge_range(9, 0, 9, 9,
        f"Generated on {datetime.now().strftime('%d %B %Y, %I:%M %p')}", cover_meta)
    cover.set_row(10, 26)
    cover.merge_range(10, 0, 10, 9, "", light_bg)

    cover.set_row(11, 20)
    cover.merge_range(11, 0, 11, 9, "  Report Sections", fmt(
        bold=True, font_size=11, font_color=_hex(PRIMARY),
        bg_color=_hex(ACCENT_LIGHT), align="left", valign="vcenter",
        font_name="Calibri", left=4, left_color=_hex(ACCENT),
    ))

    sections = [
        ("KPI Summary",          "8 headline metrics at a glance"),
        ("Campaign Breakdown",   "Performance per campaign"),
        ("Daily Trend",          "Day-by-day spend & ROAS"),
        ("Notes & Recommendations", "Agency notes and next steps"),
    ]
    for i, (name, desc) in enumerate(sections):
        r = 12 + i
        cover.set_row(r, 24)
        row_bg = _hex(WHITE) if i % 2 == 0 else _hex(LIGHT_GREY)
        cover.write(r, 0, f"  {i+1}. {name}", fmt(
            bold=True, font_size=10, font_color=_hex(ACCENT),
            bg_color=row_bg, font_name="Calibri",
        ))
        cover.merge_range(r, 1, r, 9, desc, fmt(
            font_size=10, font_color=_hex(TEXT_MID),
            bg_color=row_bg, font_name="Calibri",
        ))

    for r in range(16, 18):
        cover.set_row(r, 26)
        cover.merge_range(r, 0, r, 9, "", light_bg)

    # ── SHEET 2: KPI SUMMARY ──────────────────────────────────────────────
    ws = wb.add_worksheet("KPI Summary")
    ws.hide_gridlines(2)
    ws.set_tab_color(_hex(ACCENT))
    ws.set_column("A:A", 2)
    ws.set_column("B:E", 18)
    ws.set_column("F:I", 18)

    ws.set_row(0, 40)
    ws.merge_range(0, 0, 0, 8, f"  KPI Summary — {client_name}  ·  {date_range}",
        fmt(bold=True, font_size=14, font_color=_hex(WHITE),
            bg_color=_hex(PRIMARY), align="left", valign="vcenter",
            font_name="Calibri", left=6, left_color=_hex(ACCENT)))

    kpi_keys = [
        ("ROAS",        "roas",        "x",   True),
        ("CTR",         "ctr",         "%",   False),
        ("Total Spend", "total_spend", "₹",   False),
        ("Impressions", "impressions", "",    False),
        ("Clicks",      "clicks",      "",    False),
        ("CPC",         "cpc",         "₹",   False),
        ("Conversions", "conversions", "",    True),
        ("CPA",         "cpa",         "₹",   False),
    ]
    positions = [
        (2, 1), (2, 3), (2, 5), (2, 7),
        (5, 1), (5, 3), (5, 5), (5, 7),
    ]

    for (row, col), (label, key, unit, is_good) in zip(positions, kpi_keys):
        raw = kpi_data.get(key, 0)
        if unit == "₹":
            display = f"₹{raw:,.2f}"
        elif unit == "%":
            display = f"{raw:.2f}%"
        elif unit == "x":
            display = f"{raw:.2f}x"
        else:
            display = f"{raw:,.0f}" if isinstance(raw, (int, float)) else str(raw)

        ws.set_row(row, 18)
        ws.set_row(row + 1, 44)
        ws.merge_range(row, col, row, col + 1, label, kpi_label)
        ws.merge_range(row + 1, col, row + 1, col + 1, display,
            kpi_value_good if is_good else kpi_value)

    ws.set_row(8, 8)
    ws.set_row(9, 28)
    ws.merge_range(9, 0, 9, 8, "  Performance Insights", section_head)

    insights = _generate_insights(kpi_data)
    for i, insight in enumerate(insights):
        ws.set_row(10 + i, 22)
        ws.merge_range(10 + i, 1, 10 + i, 8,
            f"  {'✅' if insight['good'] else '⚠️'}  {insight['text']}",
            fmt(font_size=10, font_color=_hex(TEXT_DARK), font_name="Calibri",
                bg_color=_hex(WHITE) if i % 2 == 0 else _hex(LIGHT_GREY)))

    last = 10 + len(insights) + 1
    ws.set_row(last, 20)
    ws.merge_range(last, 0, last, 8,
        f"Generated by PRISM  ·  {agency_name}  ·  {datetime.now().strftime('%d %b %Y')}",
        footer_fmt)

    # ── SHEET 3: CAMPAIGN BREAKDOWN ───────────────────────────────────────
    cs = wb.add_worksheet("Campaign Breakdown")
    cs.hide_gridlines(2)
    cs.set_tab_color(_hex(ACCENT_LIGHT))
    cs.set_column("A:A", 2)
    cs.set_column("B:B", 28)
    cs.set_column("C:I", 14)
    cs.set_column("J:J", 10)

    cs.set_row(0, 40)
    cs.merge_range(0, 0, 0, 9, f"  Campaign Breakdown — {client_name}",
        fmt(bold=True, font_size=14, font_color=_hex(WHITE),
            bg_color=_hex(PRIMARY), align="left", valign="vcenter",
            font_name="Calibri"))

    headers = ["Campaign", "Spend (₹)", "Impressions", "Clicks", "CTR (%)", "CPC (₹)", "Conv.", "ROAS", "Action"]
    cs.set_row(2, 32)
    for j, h in enumerate(headers):
        cs.write(2, j + 1, h, tbl_header)

    if not campaign_rows:
        cs.merge_range(3, 1, 3, 9, "No campaign data available", tbl_row)
    else:
        for i, row in enumerate(campaign_rows):
            r = i + 3
            cs.set_row(r, 22)
            alt      = i % 2 == 1
            base_fmt = tbl_row_alt if alt else tbl_row
            curr_fmt = tbl_currency_alt if alt else tbl_currency
            pct_fmt  = tbl_pct_alt if alt else tbl_pct

            cs.write(r, 1, row.get("campaign", f"Campaign {i+1}"), base_fmt)
            cs.write(r, 2, row.get("spend", 0), curr_fmt)
            cs.write(r, 3, row.get("impressions", 0), base_fmt)
            cs.write(r, 4, row.get("clicks", 0), base_fmt)
            ctr_val = row.get("ctr", 0)
            cs.write(r, 5, ctr_val / 100 if ctr_val > 1 else ctr_val, pct_fmt)
            cs.write(r, 6, row.get("cpc", 0), curr_fmt)
            cs.write(r, 7, row.get("conversions", 0), base_fmt)
            cs.write(r, 8, row.get("roas", 0), base_fmt)

            roas_val = row.get("roas", 0)
            if roas_val >= 4.2:
                cs.write(r, 9, "⬆ Scale", tbl_scale)
            elif roas_val >= 3.9:
                cs.write(r, 9, "⏸ Hold", tbl_hold)
            else:
                cs.write(r, 9, "⏹ Pause", tbl_pause)

        chart = wb.add_chart({"type": "bar"})
        chart.add_series({
            "name":       "ROAS",
            "categories": ["Campaign Breakdown", 3, 1, 2 + len(campaign_rows), 1],
            "values":     ["Campaign Breakdown", 3, 8, 2 + len(campaign_rows), 8],
            "fill":       {"color": _hex(ACCENT)},
            "border":     {"color": _hex(PRIMARY)},
        })
        chart.set_title({"name": "ROAS by Campaign"})
        chart.set_x_axis({"name": "ROAS"})
        chart.set_legend({"none": True})
        chart.set_size({"width": 480, "height": 260})
        chart.set_chartarea({"border": {"none": True}, "fill": {"color": _hex(WHITE)}})
        cs.insert_chart(len(campaign_rows) + 5, 1, chart)

    # ── SHEET 4: DAILY TREND ──────────────────────────────────────────────
    ds = wb.add_worksheet("Daily Trend")
    ds.hide_gridlines(2)
    ds.set_column("A:A", 2)
    ds.set_column("B:B", 16)
    ds.set_column("C:D", 16)

    ds.set_row(0, 40)
    ds.merge_range(0, 0, 0, 4, f"  Daily Spend & ROAS Trend — {client_name}",
        fmt(bold=True, font_size=14, font_color=_hex(WHITE),
            bg_color=_hex(PRIMARY), align="left", valign="vcenter",
            font_name="Calibri"))

    daily_headers = ["Date", "Spend (₹)", "ROAS"]
    ds.set_row(2, 30)
    for j, h in enumerate(daily_headers):
        ds.write(2, j + 1, h, tbl_header)

    if not daily_rows:
        ds.merge_range(3, 1, 3, 3, "No daily data available", tbl_row)
    else:
        for i, row in enumerate(daily_rows):
            r = i + 3
            ds.set_row(r, 20)
            alt      = i % 2 == 1
            base_fmt = tbl_row_alt if alt else tbl_row
            curr_fmt = tbl_currency_alt if alt else tbl_currency
            ds.write(r, 1, str(row.get("date", "")), base_fmt)
            ds.write(r, 2, row.get("spend", 0), curr_fmt)
            ds.write(r, 3, row.get("roas", 0), base_fmt)

        spend_chart = wb.add_chart({"type": "line"})
        spend_chart.add_series({
            "name":       "Daily Spend",
            "categories": ["Daily Trend", 3, 1, 2 + len(daily_rows), 1],
            "values":     ["Daily Trend", 3, 2, 2 + len(daily_rows), 2],
            "line":       {"color": _hex(ACCENT), "width": 2.5},
            "marker":     {"type": "circle", "size": 5, "fill": {"color": _hex(ACCENT)}},
        })
        spend_chart.set_title({"name": "Daily Spend (₹)"})
        spend_chart.set_legend({"none": True})
        spend_chart.set_size({"width": 480, "height": 240})
        spend_chart.set_chartarea({"border": {"none": True}, "fill": {"color": _hex(WHITE)}})
        ds.insert_chart(len(daily_rows) + 5, 1, spend_chart)

        roas_chart = wb.add_chart({"type": "line"})
        roas_chart.add_series({
            "name":       "ROAS",
            "categories": ["Daily Trend", 3, 1, 2 + len(daily_rows), 1],
            "values":     ["Daily Trend", 3, 3, 2 + len(daily_rows), 3],
            "line":       {"color": _hex(GREEN), "width": 2.5},
            "marker":     {"type": "diamond", "size": 5, "fill": {"color": _hex(GREEN)}},
        })
        roas_chart.set_title({"name": "ROAS Trend"})
        roas_chart.set_legend({"none": True})
        roas_chart.set_size({"width": 480, "height": 240})
        roas_chart.set_chartarea({"border": {"none": True}, "fill": {"color": _hex(WHITE)}})
        ds.insert_chart(len(daily_rows) + 5, 4, roas_chart)

    # ── SHEET 5: NOTES & RECOMMENDATIONS ─────────────────────────────────
    ns = wb.add_worksheet("Notes & Recommendations")
    ns.hide_gridlines(2)
    ns.set_tab_color(_hex(GREEN))
    ns.set_column("A:A", 3)
    ns.set_column("B:J", 14)
    ns.set_zoom(90)

    # header
    ns.set_row(0, 50)
    ns.merge_range(0, 0, 0, 9,
        f"  Notes & Recommendations — {client_name}  ·  {date_range}",
        fmt(bold=True, font_size=16, font_color=_hex(WHITE),
            bg_color=_hex(PRIMARY), align="left", valign="vcenter",
            font_name="Calibri", left=6, left_color=_hex(ACCENT)))

    ns.set_row(1, 20)
    ns.merge_range(1, 0, 1, 9,
        f"  Prepared by {agency_name}  ·  {datetime.now().strftime('%d %B %Y')}",
        fmt(font_size=10, font_color=_hex(TEXT_MID),
            bg_color=_hex(ACCENT_LIGHT), align="left", valign="vcenter",
            font_name="Calibri", left=6, left_color=_hex(ACCENT)))

    def notes_section(ws, start_row, title, lines=4):
        """Write a branded section header + blank editable rows."""
        ws.set_row(start_row, 28)
        ws.merge_range(start_row, 0, start_row, 9, f"  {title}",
            fmt(bold=True, font_size=12, font_color=_hex(WHITE),
                bg_color=_hex(PRIMARY), align="left", valign="vcenter",
                font_name="Calibri", left=4, left_color=_hex(ACCENT)))
        editable = fmt(
            font_size=11, font_color=_hex(TEXT_DARK),
            bg_color=_hex(WHITE), align="left", valign="vcenter",
            font_name="Calibri",
            border=1, border_color=_hex(MID_GREY),
        )
        editable_alt = fmt(
            font_size=11, font_color=_hex(TEXT_DARK),
            bg_color=_hex(LIGHT_GREY), align="left", valign="vcenter",
            font_name="Calibri",
            border=1, border_color=_hex(MID_GREY),
        )
        for i in range(lines):
            r = start_row + 1 + i
            ws.set_row(r, 30)
            ws.merge_range(r, 0, r, 9, "",
                editable_alt if i % 2 == 1 else editable)
        return start_row + 1 + lines + 1  # next free row

    row = 3
    row = notes_section(ns, row, "📋  Executive Summary", lines=4)
    row = notes_section(ns, row, "🏆  Key Wins This Period", lines=4)
    row = notes_section(ns, row, "⚠️   Areas to Improve", lines=4)
    row = notes_section(ns, row, "🚀  Recommended Actions for Next Month", lines=5)
    row = notes_section(ns, row, "📅  Next Review Date & Goals", lines=3)

    # branded footer
    ns.set_row(row + 1, 20)
    ns.merge_range(row + 1, 0, row + 1, 9,
        f"Generated by PRISM  ·  {agency_name}  ·  {datetime.now().strftime('%d %b %Y')}",
        fmt(italic=True, font_size=9, font_color=_hex(TEXT_MID),
            align="right", font_name="Calibri"))

    wb.close()
    return output.getvalue()


def _generate_insights(kpi: dict) -> list[dict]:
    insights = []

    roas = kpi.get("roas", 0)
    if roas >= 4:
        insights.append({"good": True,  "text": f"ROAS of {roas:.2f}x is excellent — campaign is highly profitable."})
    elif roas >= 2:
        insights.append({"good": True,  "text": f"ROAS of {roas:.2f}x is healthy. Aim for 4x+ to maximise returns."})
    else:
        insights.append({"good": False, "text": f"ROAS of {roas:.2f}x is below target. Review creative and audience targeting."})

    ctr = kpi.get("ctr", 0)
    if ctr >= 2:
        insights.append({"good": True,  "text": f"CTR of {ctr:.2f}% is strong — ads are resonating with the audience."})
    elif ctr >= 1:
        insights.append({"good": False, "text": f"CTR of {ctr:.2f}% is average. A/B test creatives to push above 2%."})
    else:
        insights.append({"good": False, "text": f"CTR of {ctr:.2f}% is low. Consider refreshing ad copy and visuals."})

    cpc = kpi.get("cpc", 0)
    if cpc and cpc < 20:
        insights.append({"good": True,  "text": f"CPC of ₹{cpc:.2f} is efficient. Keep optimising bid strategy."})
    elif cpc:
        insights.append({"good": False, "text": f"CPC of ₹{cpc:.2f} is high. Narrow audience targeting to reduce cost."})

    convs = kpi.get("conversions", 0)
    if convs:
        insights.append({"good": True, "text": f"{convs:,.0f} conversions recorded this period."})

    if not insights:
        insights.append({"good": True, "text": "Upload campaign data to see detailed performance insights."})

    return insights