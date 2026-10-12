"""
Build the Cycle 1 Excel deliverable: outputs/sdg7_cycle1.xlsx

Reads only data/processed/ -- never the API, never data/raw/ -- so the workbook is
reproducible from the CSVs that the earlier scripts emit. Nothing in the workbook is
hand-edited; re-running this script rebuilds it from scratch.

Three tabs. The regional pivot and the data dictionary are deliberately NOT generated here -- Suyog builds that by hand
in Excel. The regional pivot must come from data/processed/sdg7_regions.csv, NOT from the Data
tab: the UN's regional figures are population-weighted, and averaging the countries on the Data
tab gives a different and wrong answer.

Three tabs:
  Data             country-year grain, as an Excel Table so a PivotTable can be inserted on it
  Top20_Gap        the two different questions side by side -- widest gap vs fastest-widening gap
  QA               live checks against the source CSVs

Nothing left in the workbook documents the sources, units or limitations -- that was the
Data_Dictionary tab's job. Recover its text with:
  git show 808af00:cycle1-sdg7/scripts/04_build_excel.py

The derived columns are written as Excel *formulas*, not as values copied out of pandas, so a
reviewer can click any gap figure and see the subtraction behind it.

Usage:  python scripts/04_build_excel.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs" / "sdg7_cycle1.xlsx"

API = "https://unstats.un.org/sdgs/UNSDGAPIV5/v1/sdg"
RETRIEVED = "2026-10-05"
ELEC, COOK, PRIM, RNEW = "EG_ACS_ELEC", "EG_EGY_CLEAN", "EG_EGY_PRIM", "EG_FEC_RNEW"

# Same palette as the matplotlib figures and the Tableau dashboard, so the three
# artefacts read as one system. Validated for colourblind separation and contrast.
BLUE, RED, WHITE = "FF2A78D6", "FFE34948", "FFFFFFFF"
HEAD_FILL = PatternFill("solid", fgColor="FF1F3F66")
BAND_FILL = PatternFill("solid", fgColor="FFF2F4F7")
NOTE_FONT = Font(name="Arial", size=9, italic=True, color="FF52514E")
TITLE_FONT = Font(name="Arial", size=13, bold=True, color="FF0B0B0B")
SECTION_FONT = Font(name="Arial", size=11, bold=True, color="FF0B0B0B")
BODY_FONT = Font(name="Arial", size=10)
HEAD_FONT = Font(name="Arial", size=10, bold=True, color=WHITE)
THIN = Side(style="thin", color="FFD9D9D9")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

PCT = "0.0"      # values arrive on a 0-100 scale; the unit lives in the header
PP = "0.0"       # percentage points
MJ = "0.00"


# ----------------------------------------------------------------------------- helpers

def write_row(ws, row, values, font=BODY_FONT, fill=None, border=False, fmt=None):
    """Write one row of values starting at column A and return the row number."""
    for i, v in enumerate(values, start=1):
        c = ws.cell(row=row, column=i, value=v)
        c.font = font
        if fill is not None:
            c.fill = fill
        if border:
            c.border = BOX
        if fmt and i > 1 and isinstance(v, (int, float)):
            c.number_format = fmt
    return row


def header_row(ws, row, labels):
    """A dark banded header: bold white on navy, wrapped, centred."""
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row=row, column=i, value=label)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BOX
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30
    return row


def set_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def blank(v):
    """pandas NaN -> None, so the cell is genuinely empty rather than the text 'nan'."""
    return None if pd.isna(v) else v


# ------------------------------------------------------------------------------- tabs

def build_data(ws, metrics: pd.DataFrame) -> int:
    """Country-year grain as an Excel Table. Returns the last data row."""
    headers = [
        "M49 code", "Country", "SDG region", "Year",
        "Electricity access (%)", "Clean cooking (%)",
        "Energy intensity (MJ/$ PPP)", "Renewable share (%)",
        "Cooking gap (pp)", "Electricity urban-rural gap (pp)",
        "Clean cooking urban-rural gap (pp)",
    ]
    header_row(ws, 1, headers)

    for i, (_, r) in enumerate(metrics.iterrows()):
        row = i + 2
        write_row(ws, row, [
            int(r.m49_code), r.country, r.region, int(r.year),
            blank(r[ELEC]), blank(r[COOK]), blank(r[PRIM]), blank(r[RNEW]),
            # Computed in the sheet, not copied from pandas: a reviewer can see the
            # subtraction. Blank when either input is missing, so no fake zeros appear.
            f"=IF(OR(E{row}=\"\",F{row}=\"\"),\"\",E{row}-F{row})",
            blank(r.elec_urban_rural_gap), blank(r.cook_urban_rural_gap),
        ])
        for col, fmt in ((5, PCT), (6, PCT), (7, MJ), (8, PCT),
                         (9, PP), (10, PP), (11, PP)):
            ws.cell(row=row, column=col).number_format = fmt

    last = len(metrics) + 1
    table = Table(displayName="SDG7Data", ref=f"A1:K{last}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleLight9", showRowStripes=True, showColumnStripes=False)
    ws.add_table(table)

    ws.freeze_panes = "C2"
    set_widths(ws, [10, 34, 30, 7, 13, 12, 14, 12, 12, 15, 15])
    return last


def build_top20(ws, summary: pd.DataFrame) -> dict:
    """The two questions the research question deliberately asks separately."""
    ws.cell(row=1, column=1, value="Widest gap and fastest-widening gap are different lists").font = TITLE_FONT
    c = ws.cell(row=2, column=1, value=(
        "'Where is the gap widest?' is a question about the level in 2024. 'Where is it still growing?' is a "
        "question about the change since 2015. They rank largely different countries, which is why both blocks "
        "are here and why the deck asks both. The last column of each block is a live COUNTIF against the other."))
    c.font, c.alignment = NOTE_FONT, Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=2, start_column=1, end_row=3, end_column=9)

    widest = summary.dropna(subset=["gap_2024"]).nlargest(20, "gap_2024").reset_index(drop=True)
    widening = summary.dropna(subset=["gap_change"]).nlargest(20, "gap_change").reset_index(drop=True)

    row = 5
    ws.cell(row=row, column=1, value="A. The 20 widest cooking gaps in 2024 (a question about LEVEL)").font = SECTION_FONT
    row += 1
    header_row(ws, row, ["Rank", "Country", "SDG region", "Electricity 2024 (%)",
                         "Clean cooking 2024 (%)", "Gap 2024 (pp)", "Gap 2015 (pp)",
                         "Change 2015-2024 (pp)", "Also in list B?"])
    row += 1
    a_start = row
    for i, r in widest.iterrows():
        write_row(ws, row, [i + 1, r.country, r.region, blank(r.elec_2024), blank(r.cook_2024)],
                  fill=BAND_FILL if i % 2 else None, border=True, fmt=PCT)
        row += 1
    a_last = row - 1

    row += 1
    ws.cell(row=row, column=1, value="B. The 20 fastest-widening cooking gaps, 2015-2024 (a question about CHANGE)").font = SECTION_FONT
    row += 1
    header_row(ws, row, ["Rank", "Country", "SDG region", "Electricity 2024 (%)",
                         "Clean cooking 2024 (%)", "Gap 2024 (pp)", "Gap 2015 (pp)",
                         "Change 2015-2024 (pp)", "Also in list A?"])
    row += 1
    b_start = row
    for i, r in widening.iterrows():
        write_row(ws, row, [i + 1, r.country, r.region, blank(r.elec_2024), blank(r.cook_2024)],
                  fill=BAND_FILL if i % 2 else None, border=True, fmt=PCT)
        row += 1
    b_last = row - 1

    # Gap, 2015 level and change are all computed in the sheet. The 2015 gap is looked up
    # out of the Data tab rather than copied, so the two tabs cannot drift apart.
    for start, last, other_start, other_last in ((a_start, a_last, b_start, b_last),
                                                 (b_start, b_last, a_start, a_last)):
        for rr in range(start, last + 1):
            f = ws.cell(row=rr, column=6, value=f"=IF(OR(D{rr}=\"\",E{rr}=\"\"),\"\",D{rr}-E{rr})")
            g = ws.cell(row=rr, column=7,
                        value=(f"=IFERROR(SUMIFS(Data!$I$2:$I${DATA_LAST},Data!$B$2:$B${DATA_LAST},$B{rr},"
                               f"Data!$D$2:$D${DATA_LAST},2015),\"\")"))
            h = ws.cell(row=rr, column=8, value=f"=IF(OR(F{rr}=\"\",G{rr}=\"\"),\"\",F{rr}-G{rr})")
            k = ws.cell(row=rr, column=9,
                        value=f"=IF(COUNTIF($B${other_start}:$B${other_last},$B{rr})>0,\"yes\",\"-\")")
            for cell, fmt in ((f, PP), (g, PP), (h, "+0.0;-0.0;0.0")):
                cell.number_format = fmt
            for cell in (f, g, h, k):
                cell.font, cell.border = BODY_FONT, BOX
                if (rr - start) % 2:
                    cell.fill = BAND_FILL
            k.alignment = Alignment(horizontal="center")

    for start, last in ((a_start, a_last), (b_start, b_last)):
        ws.conditional_formatting.add(
            f"H{start}:H{last}",
            ColorScaleRule(start_type="num", start_value=-45, start_color=BLUE,
                           mid_type="num", mid_value=0, mid_color=WHITE,
                           end_type="num", end_value=45, end_color=RED))

    overlap = sorted(set(widest.country) & set(widening.country))
    ws.cell(row=b_last + 2, column=1, value=(
        f"{len(overlap)} of 20 countries appear in both blocks: "
        f"{', '.join(overlap) if overlap else 'none'}.")).font = NOTE_FONT

    set_widths(ws, [6, 34, 30, 13, 13, 11, 11, 13, 13])
    return {"a_start": a_start, "a_last": a_last, "b_start": b_start, "b_last": b_last}


def build_qa(ws, top: dict, expect: dict):
    """Live checks. Every 'In workbook' figure is a formula reading the other tabs."""
    ws.cell(row=1, column=1, value="QA: live checks against the Data tab").font = TITLE_FONT
    c = ws.cell(row=2, column=1, value=(
        "Nothing here is a typed-in number except the 'Expected' column, which records what the source "
        "publishes. Every 'In workbook' cell is a formula, so if the Data tab ever changes these checks "
        "move with it and the verdict flips."))
    c.font, c.alignment = NOTE_FONT, Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=2, start_column=1, end_row=3, end_column=5)

    D, L = "Data", DATA_LAST
    row = 5
    ws.cell(row=row, column=1, value="1. Shape").font = SECTION_FONT
    row += 1
    header_row(ws, row, ["Check", "Expected", "In workbook", "Verdict", "Note"])
    row += 1
    shape = [
        ("Rows of data", expect["rows"], f"=COUNTA({D}!$B$2:$B${L})", ""),
        ("Distinct countries", expect["countries"], f"=COUNTIF({D}!$D$2:$D${L},2015)",
         "Each country has one row per year, so counting the 2015 rows counts the countries."),
        ("Countries with a 2024 row", expect["countries_2024"], f"=COUNTIF({D}!$D$2:$D${L},2024)",
         "One short of the total: Kosovo's series ends in 2023."),
        ("First year", 2015, f"=MIN({D}!$D$2:$D${L})", "Window set by the ISS brief."),
        ("Last year", 2024, f"=MAX({D}!$D$2:$D${L})", ""),
        ("Duplicate country-year keys", 0,
         f"=SUMPRODUCT(--(COUNTIFS({D}!$B$2:$B${L},{D}!$B$2:$B${L},{D}!$D$2:$D${L},{D}!$D$2:$D${L})>1))",
         "Must be 0. A duplicate key would be silently AVERAGED by any PivotTable built on this "
         "tab rather than raising an error, so it is worth re-checking after any change upstream."),
    ]
    for name, exp, formula, note in shape:
        write_row(ws, row, [name, exp, formula, f"=IF(ROUND(C{row},6)=ROUND(B{row},6),\"PASS\",\"FAIL\")", note],
                  border=True)
        ws.cell(row=row, column=5).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    shape_rows = (row - len(shape), row - 1)

    row += 1
    ws.cell(row=row, column=1, value="2. Completeness by indicator").font = SECTION_FONT
    row += 1
    header_row(ws, row, ["Indicator column", "Values present", "Blank", "% complete", "Note"])
    row += 1
    for col, label, note in (("E", "Electricity access (7.1.1)", ""),
                             ("F", "Clean cooking (7.1.2)", ""),
                             ("G", "Energy intensity (7.3.1)", "Lags about two years."),
                             ("H", "Renewable share (7.2.1)", "Thin after 2022 -- the known limitation.")):
        write_row(ws, row, [
            label,
            f"=COUNT({D}!${col}$2:${col}${L})",
            f"=COUNTA({D}!$B$2:$B${L})-COUNT({D}!${col}$2:${col}${L})",
            f"=B{row}/COUNTA({D}!$B$2:$B${L})",
            note,
        ], border=True)
        ws.cell(row=row, column=4).number_format = "0.0%"
        ws.cell(row=row, column=5).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="3. The cooking-gap invariant").font = SECTION_FONT
    row += 1
    header_row(ws, row, ["Check", "Expected", "In workbook", "Verdict", "Note"])
    row += 1
    # Both indicators are shares of population, so ">=0" is exactly "a number is present"
    # and nothing else. COUNTIFS and COUNT are used rather than SUMPRODUCT over ISNUMBER
    # because array broadcasting inside SUMPRODUCT is not portable across spreadsheet
    # engines, and a check that silently returns zero is worse than no check at all.
    both = f"COUNTIFS({D}!$E$2:$E${L},\">=0\",{D}!$F$2:$F${L},\">=0\")"
    gaps = f"COUNT({D}!$I$2:$I${L})"
    inv = [
        ("Rows with both inputs present", expect["both_inputs"], f"={both}",
         "Counted as cells holding a number >= 0, which both indicators always are."),
        ("Rows with a cooking gap", expect["both_inputs"], f"={gaps}",
         "Must equal the row above: the gap exists exactly where both inputs do, never anywhere else."),
        ("Difference", 0, f"={both}-{gaps}", "Any non-zero value means a gap was invented or lost."),
    ]
    for name, exp, formula, note in inv:
        write_row(ws, row, [name, exp, formula, f"=IF(C{row}=B{row},\"PASS\",\"FAIL\")", note], border=True)
        ws.cell(row=row, column=5).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    inv_rows = (row - len(inv), row - 1)

    row += 1
    ws.cell(row=row, column=1, value="4. Spot-checks against published UN values").font = SECTION_FONT
    row += 1
    header_row(ws, row, ["Check", "Expected", "In workbook", "Verdict", "Note"])
    row += 1
    spot = [
        ("Nepal 2023, clean cooking, all areas", 44,
         f"=SUMIFS({D}!$F$2:$F${L},{D}!$B$2:$B${L},\"Nepal\",{D}!$D$2:$D${L},2023)",
         "Published by WHO as urban 63 / rural 24 / all areas 44."),
        ("Afghanistan 2024, clean cooking, all areas", 30,
         f"=SUMIFS({D}!$F$2:$F${L},{D}!$B$2:$B${L},\"Afghanistan\",{D}!$D$2:$D${L},2024)",
         "All-areas value, range 15-48. The 78 often quoted for Afghanistan is the URBAN figure -- "
         "the two are easy to confuse and differ by 48 pp."),
        ("Lao PDR 2024, cooking gap", 86.5,
         f"=SUMIFS({D}!$I$2:$I${L},{D}!$B$2:$B${L},\"Lao People's Democratic Republic\",{D}!$D$2:$D${L},2024)",
         "The widest gap in the dataset: 96.5% electricity against 10% clean cooking."),
        ("Rwanda, change in gap 2015-2024", 41.2,
         f"=IFERROR(INDEX(Top20_Gap!$H${top['b_start']}:$H${top['b_last']},"
         f"MATCH(\"Rwanda\",Top20_Gap!$B${top['b_start']}:$B${top['b_last']},0)),\"not in list\")",
         "The fastest-widening gap in the dataset."),
    ]
    for name, exp, formula, note in spot:
        write_row(ws, row, [name, exp, formula, f"=IF(ROUND(C{row},1)=ROUND(B{row},1),\"PASS\",\"FAIL\")", note],
                  border=True)
        for col in (2, 3):
            ws.cell(row=row, column=col).number_format = "0.0"
        ws.cell(row=row, column=5).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = 30
        row += 1
    spot_rows = (row - len(spot), row - 1)

    row += 1
    ws.cell(row=row, column=1, value="5. Known source revisions, not cleaning errors").font = SECTION_FONT
    row += 1
    header_row(ws, row, ["Country", "Years", "Jump (pp)", "Indicator", "Note"])
    row += 1
    for vals in [
        ["Afghanistan", "2015 to 2016", 26.2, "Electricity access (7.1.1)",
         "The only three year-on-year moves above 20 pp anywhere in the two access series. They "
         "survive cleaning on purpose: smoothing them would hide a revision the source actually made."],
        ["Papua New Guinea", "2023 to 2024", 22.8, "Electricity access (7.1.1)", ""],
        ["Cambodia", "2016 to 2017", 20.3, "Electricity access (7.1.1)", ""],
    ]:
        write_row(ws, row, vals, border=True, fmt="+0.0")
        ws.cell(row=row, column=5).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = 30
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="6. Verdict").font = SECTION_FONT
    row += 1
    blocks = (shape_rows, inv_rows, spot_rows)
    terms = "+".join(f"COUNTIF($D${lo}:$D${hi},\"FAIL\")" for lo, hi in blocks)
    total = sum(hi - lo + 1 for lo, hi in blocks)
    ws.cell(row=row, column=1, value=f"All {total} pass/fail checks above").font = BODY_FONT
    v = ws.cell(row=row, column=2,
                value=f"=IF({terms}=0,\"ALL PASS\",\"SOME FAILED - do not ship\")")
    v.font, v.border = Font(name="Arial", size=11, bold=True), BOX
    ws.cell(row=row, column=5, value=(
        "This is the one cell to look at before using the workbook.")).font = NOTE_FONT

    set_widths(ws, [40, 14, 14, 12, 62])


# -------------------------------------------------------------------------------- main

def main() -> int:
    for f in ("sdg7_country_metrics.csv", "sdg7_country_summary.csv"):
        if not (PROC / f).exists():
            print(f"FAIL  missing {PROC / f} -- run scripts 01-03 first")
            return 1

    metrics = pd.read_csv(PROC / "sdg7_country_metrics.csv").sort_values(["country", "year"])
    summary = pd.read_csv(PROC / "sdg7_country_summary.csv")

    expect = {
        "rows": len(metrics),
        "countries": int(metrics.country.nunique()),
        "countries_2024": int((metrics.year == 2024).sum()),
        "both_inputs": int((metrics[ELEC].notna() & metrics[COOK].notna()).sum()),
    }

    global DATA_LAST
    DATA_LAST = len(metrics) + 1

    wb = Workbook()
    ws_data = wb.active
    ws_data.title = "Data"

    build_data(ws_data, metrics)
    top = build_top20(wb.create_sheet("Top20_Gap"), summary)
    build_qa(wb.create_sheet("QA"), top, expect)

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = True

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)

    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  Data             {expect['rows']:>5} rows x 11 cols  (Excel Table 'SDG7Data', A1:K{DATA_LAST})")
    print(f"  Top20_Gap        {20:>5} widest + {20} fastest-widening")
    print(f"  QA                    live checks in 6 sections")
    print()
    print("No regional pivot and no data dictionary: both are built by hand.")
    print("The pivot must come from data/processed/sdg7_regions.csv -- NOT from")
    print("the Data tab, whose countries cannot be averaged into a correct")
    print("regional figure. Nothing in the workbook now records the sources,")
    print("units or limitations.")
    print()
    print("openpyxl writes formulas without cached values, so the formula cells read as")
    print("empty until Excel (or LibreOffice) opens and recalculates the file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
