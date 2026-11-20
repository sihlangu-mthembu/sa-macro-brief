"""Build the Excel workbook. Source data is written as values (blue = data pulled from a
source); every change figure is an Excel formula, so the sheet recalculates if a value
is corrected by hand."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.axis import DateAxis
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L

from . import config
from .analyse import PERIODS

F = "Arial"
NAVY, GREEN, RED, GREY, BLUE = "0B1F4B", "007A3D", "C0392B", "6B7280", "0000FF"
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
BAND = PatternFill("solid", fgColor="F3F5F9")
THIN = Border(bottom=Side(style="thin", color="D9DEE7"))
PCT = '+0.0%;-0.0%;0.0%'
PP = '+0.00" pp";-0.00" pp";0.00" pp"'


def font(size=10, bold=False, color="111827", italic=False, underline=None):
    return Font(name=F, size=size, bold=bold, color=color, italic=italic, underline=underline)


def header(ws, row, labels, col=1):
    for i, h in enumerate(labels):
        c = ws.cell(row, col + i, h)
        c.font = font(10, True, "FFFFFF")
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="left" if i == 0 else "center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 22


def title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = font(16, True, NAVY)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = font(9, color=GREY, italic=True)
    ws.sheet_view.showGridLines = False


def value_fmt(unit):
    return "0.00" if unit in ("%",) else ("#,##0.0000" if unit.startswith("R per") else "#,##0.00")


def colour_changes(ws, rng):
    ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["0"], font=Font(name=F, color=GREEN)))
    ws.conditional_formatting.add(rng, CellIsRule(operator="lessThan", formula=["0"], font=Font(name=F, color=RED)))


def para_rows(ws, row, text, width_chars=150, size=10, bold=False, color="111827", last_col=9):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    c = ws.cell(row, 1, text)
    c.font = font(size, bold, color)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    lines = max(1, math.ceil(len(text) / width_chars))
    ws.row_dimensions[row].height = max(16, lines * (size + 5))
    return row + 1


def build(path, run_ts: dt.datetime, markets: pd.DataFrame, snap, sarb, news, brief, history: pd.DataFrame, errors):
    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True
    ws = wb.active
    ws.title = "Brief"
    ch_ws = wb.create_sheet("Charts")
    cg = wb.create_sheet("Changes")
    md = wb.create_sheet("Market data")
    sb = wb.create_sheet("SARB")
    nw = wb.create_sheet("News")
    hs = wb.create_sheet("History")
    ab = wb.create_sheet("About")

    # ------------------------------------------------ Market data (raw closes)
    title(md, "Market data: daily closes", "Source: Yahoo Finance (ECB reference rates if Yahoo fails). Blue = data from source.")
    keys = [r["key"] for r in snap]
    meta = {k: (lbl, unit) for k, lbl, _, unit, *_ in config.MARKETS}
    header(md, 4, ["Date"] + [f"{meta[k][0]} ({meta[k][1]})" for k in keys])
    data = markets[keys].dropna(how="all")
    for i, (d, row) in enumerate(data.iterrows()):
        r = 5 + i
        md.cell(r, 1, d.date()).number_format = "yyyy-mm-dd"
        md.cell(r, 1).font = font()
        for j, k in enumerate(keys):
            v = row[k]
            if pd.notna(v):
                c = md.cell(r, 2 + j, float(v))
                c.number_format = value_fmt(meta[k][1])
                c.font = font(color=BLUE)
    md_last = 4 + len(data)
    md.column_dimensions["A"].width = 12
    for j in range(len(keys)):
        md.column_dimensions[L(2 + j)].width = 16
    md.freeze_panes = "B5"

    # ------------------------------------------------ Changes (reference values + formulas)
    title(cg, "Changes: how each figure is calculated",
          "Reference values are the last close on or before each reference date (blue = data). "
          "Changes are formulas: % change for prices, percentage-point change for yields.")
    cols = ["Indicator", "Unit", "Type", "Latest", "As of"] + [f"{p} ref" for p in PERIODS] + PERIODS + [f"{p} ref date" for p in PERIODS]
    header(cg, 4, cols)
    for i, r in enumerate(snap):
        row = 5 + i
        cg.cell(row, 1, r["label"]).font = font(bold=True)
        cg.cell(row, 2, r["unit"]).font = font(color=GREY)
        cg.cell(row, 3, r["kind"]).font = font(color=GREY)
        c = cg.cell(row, 4, r["value"]); c.font = font(color=BLUE); c.number_format = value_fmt(r["unit"])
        c = cg.cell(row, 5, r["date"].date()); c.number_format = "dd mmm yyyy"; c.font = font()
        for j, p in enumerate(PERIODS):
            d, v = r["refs"][p]
            ref_col, chg_col, date_col = 6 + j, 11 + j, 16 + j
            if v is not None:
                c = cg.cell(row, ref_col, v); c.font = font(color=BLUE); c.number_format = value_fmt(r["unit"])
                c = cg.cell(row, date_col, d.date()); c.number_format = "dd mmm yyyy"; c.font = font(color=GREY)
            R = f"{L(ref_col)}{row}"
            f = f'=IF({R}="","",D{row}-{R})' if r["kind"] == "yield" else f'=IF(OR({R}="",{R}=0),"",D{row}/{R}-1)'
            c = cg.cell(row, chg_col, f)
            c.number_format = PP if r["kind"] == "yield" else PCT
            c.font = font()
    last = 4 + len(snap)
    colour_changes(cg, f"K5:O{last}")
    cg.column_dimensions["A"].width = 32
    for col in range(2, 21):
        cg.column_dimensions[L(col)].width = 12
    cg.freeze_panes = "B5"

    # ------------------------------------------------ SARB
    title(sb, "South African Reserve Bank indicators", "Source: SARB web API (custom.resbank.co.za), as published on the run date.")
    header(sb, 4, ["Indicator", "Value", "Unit", "As of", "Section", "SARB series code"])
    for i, x in enumerate(sarb):
        row = 5 + i
        sb.cell(row, 1, x["name"]).font = font(bold=True)
        c = sb.cell(row, 2, x["value"]); c.font = font(color=BLUE)
        c.number_format = "#,##0.0000" if x["unit"] == "R" else "0.00"
        sb.cell(row, 3, x["unit"]).font = font(color=GREY)
        try:
            c = sb.cell(row, 4, dt.date.fromisoformat(x["date"])); c.number_format = "dd mmm yyyy"
        except ValueError:
            sb.cell(row, 4, x["date"])
        sb.cell(row, 4).font = font()
        sb.cell(row, 5, x["section"]).font = font(color=GREY)
        sb.cell(row, 6, x["code"]).font = font(color=GREY)
    for col, w in zip("ABCDEF", (44, 12, 8, 13, 26, 18)):
        sb.column_dimensions[col].width = w

    # ------------------------------------------------ News
    title(nw, "Headlines (last 36 hours)", "Sources: Google News, Moneyweb, BusinessTech, Daily Maverick RSS. Tagged stories first.")
    header(nw, 4, ["Published (SAST)", "Source", "Headline", "Tags"])
    for i, n in enumerate(news):
        row = 5 + i
        c = nw.cell(row, 1, n["published"].replace(tzinfo=None)); c.number_format = "dd mmm hh:mm"; c.font = font(color=GREY)
        nw.cell(row, 2, n["source"]).font = font(color=GREY)
        c = nw.cell(row, 3, n["title"])
        if n["link"]:
            c.hyperlink = n["link"]
            c.font = font(color="1D4ED8", underline="single")
        else:
            c.font = font()
        c.alignment = Alignment(wrap_text=True, vertical="top")
        nw.cell(row, 4, ", ".join(n["tags"])).font = font(color=GREY)
        for col in range(1, 5):
            nw.cell(row, col).border = THIN
            nw.cell(row, col).alignment = Alignment(wrap_text=True, vertical="top")
    for col, w in zip("ABCD", (16, 20, 90, 34)):
        nw.column_dimensions[col].width = w
    nw.freeze_panes = "A5"

    # ------------------------------------------------ History
    title(hs, "History: one row per run", "Built up by the daily workflow (data/history.csv in the repo). Use it for trend analysis.")
    if not history.empty:
        wide = history.pivot_table(index="run_date", columns="series", values="value", aggfunc="last").sort_index()
        header(hs, 4, ["Run date"] + list(wide.columns))
        for i, (d, row) in enumerate(wide.iterrows()):
            hs.cell(5 + i, 1, d).font = font()
            for j, v in enumerate(row):
                if pd.notna(v):
                    c = hs.cell(5 + i, 2 + j, float(v)); c.font = font(color=BLUE); c.number_format = "#,##0.00##"
        hs.column_dimensions["A"].width = 12
        for j in range(len(wide.columns)):
            hs.column_dimensions[L(2 + j)].width = 15
        hs.row_dimensions[4].height = 58
        hs.freeze_panes = "B5"

    # ------------------------------------------------ Charts
    title(ch_ws, "Charts: last 12 months", "Drawn from the Market data sheet.")
    col_of = {k: 2 + j for j, k in enumerate(keys)}
    dates = Reference(md, min_col=1, min_row=5, max_row=md_last)
    specs = [("USD/ZAR (rand per dollar; up = weaker rand)", ["usdzar"]),
             ("JSE Top 40 proxy (Satrix 40 ETF, cents)", ["top40"]),
             ("Gold and platinum ($/oz)", ["gold", "platinum"]),
             ("Brent crude ($/bbl)", ["brent"])]
    pos = ["A4", "K4", "A24", "K24"]
    for (name, ks), anchor in zip(specs, pos):
        ks = [k for k in ks if k in col_of]
        if not ks:
            continue
        chart = LineChart()
        chart.title = name
        chart.style = 2
        chart.height, chart.width = 9, 16.5
        chart.roundedCorners = False
        chart.display_blanks = "span"
        for k in ks:
            ref = Reference(md, min_col=col_of[k], min_row=4, max_row=md_last)
            chart.add_data(ref, titles_from_data=True)
        chart.set_categories(dates)
        vals = pd.concat([markets[k] for k in ks]).dropna()
        if len(vals):
            lo, hi = float(vals.min()), float(vals.max())
            pad = (hi - lo) * 0.08 or abs(hi) * 0.05
            step = 10 ** math.floor(math.log10(max(hi - lo, 1e-9)))
            chart.y_axis.scaling.min = math.floor((lo - pad) / step) * step
            chart.y_axis.scaling.max = math.ceil((hi + pad) / step) * step
        chart.y_axis.number_format = "#,##0.00" if max(abs(vals.max()), 1) < 100 else "#,##0"
        chart.x_axis = DateAxis(crossAx=100)
        chart.x_axis.number_format = "mmm yy"
        chart.x_axis.majorTimeUnit = "months"
        chart.y_axis.crossAx = 500
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        palette = ["0B1F4B", "C9A227"]
        for s, colr in zip(chart.series, palette):
            s.graphicalProperties.line.solidFill = colr
            s.graphicalProperties.line.width = 19050
            s.smooth = False
        if len(ks) > 1:
            chart.legend.position = "b"
            chart.legend.overlay = False
        else:
            chart.legend = None
        chart.title.overlay = False
        ch_ws.add_chart(chart, anchor)

    # ------------------------------------------------ Brief (front page)
    title(ws, "SA Macro & Markets Brief")
    latest_mkt = max((r["date"] for r in snap), default=None)
    ws["A2"] = (f"{run_ts:%A %d %B %Y} · prepared {run_ts:%H:%M} SAST"
                + (f" · market closes to {latest_mkt:%d %b %Y}" if latest_mkt is not None else ""))
    ws["A2"].font = font(9, color=GREY, italic=True)
    widths = [36, 10, 13, 13, 10, 10, 10, 10, 10]
    for i, w in enumerate(widths):
        ws.column_dimensions[L(i + 1)].width = w

    row = 4
    row = para_rows(ws, row, brief["headline"], width_chars=95, size=14, bold=True, color=NAVY)
    ws.row_dimensions[4].height = 24 if len(brief["headline"]) < 95 else 44
    row += 1
    for heading, items in (("What moved", brief["what_moved"]), ("So what for business", brief["so_what"]),
                           ("Watch", brief["watch"])):
        if not items:
            continue
        c = ws.cell(row, 1, heading.upper()); c.font = font(9, True, GREEN)
        row += 1
        for it in items:
            row = para_rows(ws, row, f"•  {it}", width_chars=125)
        row += 1

    # markets table, linked to the Changes sheet
    c = ws.cell(row, 1, "MARKETS"); c.font = font(9, True, GREEN)
    row += 1
    header(ws, row, ["Indicator", "Unit", "Latest", "As of"] + PERIODS)
    row += 1
    first = row
    for i, r in enumerate(snap):
        src = 5 + i
        ws.cell(row, 1, f"=Changes!A{src}").font = font(color=GREEN)
        ws.cell(row, 2, f"=Changes!B{src}").font = font(color=GREY)
        c = ws.cell(row, 3, f"=Changes!D{src}"); c.number_format = value_fmt(r["unit"]); c.font = font(bold=True)
        c = ws.cell(row, 4, f"=Changes!E{src}"); c.number_format = "dd mmm"; c.font = font(color=GREY)
        for j in range(5):
            c = ws.cell(row, 5 + j, f"=Changes!{L(11 + j)}{src}")
            c.number_format = PP if r["kind"] == "yield" else PCT
            c.font = font()
        for col in range(1, 10):
            ws.cell(row, col).border = THIN
            if i % 2:
                ws.cell(row, col).fill = BAND
            if col > 1:
                ws.cell(row, col).alignment = Alignment(horizontal="center")
        row += 1
    if snap:
        colour_changes(ws, f"E{first}:I{row - 1}")
    row += 1

    if sarb:
        c = ws.cell(row, 1, "SARB INDICATORS"); c.font = font(9, True, GREEN)
        row += 1
        header(ws, row, ["Indicator", "Value", "As of"])
        row += 1
        for i, x in enumerate(sarb):
            src = 5 + i
            ws.cell(row, 1, f"=SARB!A{src}").font = font(color=GREEN)
            c = ws.cell(row, 2, f"=SARB!B{src}"); c.number_format = "#,##0.0000" if x["unit"] == "R" else "0.00"; c.font = font(bold=True)
            c = ws.cell(row, 3, f"=SARB!D{src}"); c.number_format = "dd mmm yyyy"; c.font = font(color=GREY)
            for col in range(1, 4):
                ws.cell(row, col).border = THIN
                if col > 1:
                    ws.cell(row, col).alignment = Alignment(horizontal="center")
            row += 1
        row += 1

    if news:
        c = ws.cell(row, 1, "TOP HEADLINES"); c.font = font(9, True, GREEN)
        row += 1
        refs = [i for i in brief.get("headline_refs", []) if isinstance(i, int) and 0 <= i < len(news)]
        order = refs + [i for i in range(len(news)) if i not in refs]
        for i in order[:8]:
            n = news[i]
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
            c = ws.cell(row, 1, n["title"])
            if n["link"]:
                c.hyperlink = n["link"]
            c.font = font(color="1D4ED8", underline="single" if n["link"] else None)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row].height = 16 if len(n["title"]) < 100 else 30
            ws.merge_cells(start_row=row, start_column=8, end_row=row, end_column=9)
            c = ws.cell(row, 8, n["source"]); c.font = font(8, color=GREY); c.alignment = Alignment(vertical="top", wrap_text=True)
            row += 1
        row += 1

    note = f"Written by: {brief.get('engine', '')}. Figures come from the linked sheets; nothing here is investment advice."
    row = para_rows(ws, row, note, size=8, color=GREY)
    if errors:
        row = para_rows(ws, row, "Data issues this run: " + "; ".join(errors), size=8, color=RED)
    ws.freeze_panes = "A4"
    ws.sheet_properties.tabColor = GREEN
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0

    # ------------------------------------------------ About
    title(ab, "About this workbook")
    lines = [
        ("What it is", "An automated morning brief on South African macro and markets, built every weekday by a Python script on GitHub Actions."),
        ("Markets", "Yahoo Finance daily closes (rand crosses, Satrix 40 ETF as a JSE Top 40 proxy, S&P 500, MSCI EM ETF, gold, platinum, Brent, copper, US 10-year yield)."),
        ("Rand fallback", "European Central Bank reference rates via api.frankfurter.app, used only if Yahoo fails."),
        ("SARB", "South African Reserve Bank web API: policy rate, prime, CPI, PPI, government bond yields, ZARONIA, SABOR, official rand rates."),
        ("News", "RSS: Google News (SA economy query), Moneyweb, BusinessTech, Daily Maverick. Last 36 hours, de-duplicated, tagged by keyword."),
        ("AI analyst", "GitHub Models (free inside GitHub Actions). It sees only the figures and headlines in this workbook and is told not to invent facts. A rule-based summary is used if it is unavailable."),
        ("Colour code", "Blue = data from a source. Black = formulas. Green = links to another sheet. Changes: green up, red down (for USD/ZAR, up means a weaker rand)."),
        ("Change maths", "Prices: latest / reference - 1. Yields: latest - reference, in percentage points. Reference = last close on or before the reference date."),
        ("Disclaimer", "For information only. Not investment advice. Check figures against the original sources before relying on them."),
    ]
    for i, (k, v) in enumerate(lines):
        ab.cell(3 + i, 1, k).font = font(bold=True)
        c = ab.cell(3 + i, 2, v); c.font = font(); c.alignment = Alignment(wrap_text=True, vertical="top")
        ab.row_dimensions[3 + i].height = 30
    ab.column_dimensions["A"].width = 16
    ab.column_dimensions["B"].width = 120

    for s in wb.worksheets:
        s.sheet_view.zoomScale = 100
    wb.save(path)
