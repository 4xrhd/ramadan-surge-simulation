"""Write results.xlsx with live Excel formulas (openpyxl).

Sheets: Data, Surge, Risk, Scenarios, Backtest, Assumptions.
Formulas (newer functions carry the _xlfn. prefix Excel requires in the file) let a reader reproduce the key numbers in Excel; every formula
block sits next to the value Python computed, so the two can be compared.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="F1F5F9")
HEADER_FONT = Font(bold=True, color="000000")
THIN = Side(style="thin", color="000000")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)


def _header(ws, row: int, col: int, labels: list[str]) -> None:
    for j, label in enumerate(labels):
        cell = ws.cell(row=row, column=col + j, value=label)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BOX
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _title(ws, row: int, text: str) -> None:
    ws.cell(row=row, column=1, value=text).font = Font(bold=True, size=12)


def _widths(ws, width: int = 14) -> None:
    for col in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _data_sheet(wb: Workbook, data: pd.DataFrame, flags: pd.Series) -> None:
    ws = wb.create_sheet("Data")
    _title(ws, 1, "Cleaned monthly retail prices (BDT). Source: WFP via HDX, see Assumptions.")
    _header(ws, 2, 1, ["Month", "Ramadan flag month (1 = yes)", *data.columns])
    for i, (month, row) in enumerate(data.iterrows(), start=3):
        ws.cell(row=i, column=1, value=month.to_pydatetime()).number_format = "yyyy-mm"
        ws.cell(row=i, column=2, value=int(flags.get(month, 0)))
        for j, v in enumerate(row, start=3):
            ws.cell(row=i, column=j, value=None if pd.isna(v) else round(float(v), 4))
    ws.freeze_panes = "C3"
    _widths(ws, 16)


def _surge_block(ws, top: int, title: str, wide: pd.DataFrame, commodities: list[str]) -> int:
    """wide: index year, columns MultiIndex (commodity, field) with baseline_m1/m2, flag."""
    _title(ws, top, title)
    labels = ["Year", "Marginal"]
    for c in commodities:
        labels += [f"{c} baseline M1", f"{c} baseline M2", f"{c} baseline (AVERAGE)",
                   f"{c} flag month", f"{c} surge (formula)"]
    _header(ws, top + 1, 1, labels)
    first = top + 2
    for i, (year, row) in enumerate(wide.iterrows()):
        r = first + i
        ws.cell(row=r, column=1, value=int(year))
        ws.cell(row=r, column=2, value="yes" if bool(row[("all", "marginal")]) else "no")
        for k, c in enumerate(commodities):
            col = 3 + 5 * k
            m1, m2, f = (row.get((c, x)) for x in ("baseline_m1", "baseline_m2", "flag"))
            if pd.isna(m1) or pd.isna(m2) or pd.isna(f):
                continue
            ws.cell(row=r, column=col, value=round(float(m1), 4))
            ws.cell(row=r, column=col + 1, value=round(float(m2), 4))
            a, b, fl = (get_column_letter(col + d) for d in (0, 1, 3))
            ws.cell(row=r, column=col + 2, value=f"=AVERAGE({a}{r}:{b}{r})")
            ws.cell(row=r, column=col + 3, value=round(float(f), 4))
            base = get_column_letter(col + 2)
            ws.cell(row=r, column=col + 4, value=f"={fl}{r}/{base}{r}-1").number_format = "0.0%"
    last = first + len(wide) - 1
    stats_rows = [("n", "COUNT({r})", "0"), ("Mean", "AVERAGE({r})", "0.0%"),
                  ("SD", "_xlfn.STDEV.S({r})", "0.0%"), ("Min", "MIN({r})", "0.0%"),
                  ("Max", "MAX({r})", "0.0%"), ("CV (SD / |mean|)", None, "0.00"),
                  ("P(surge > 10%) empirical", 'COUNTIF({r},">0.1")/COUNT({r})', "0.0%"),
                  ("P5 (PERCENTILE.INC)", "_xlfn.PERCENTILE.INC({r},0.05)", "0.0%"),
                  ("P95 (PERCENTILE.INC)", "_xlfn.PERCENTILE.INC({r},0.95)", "0.0%")]
    s0 = last + 2
    for i, (label, formula, fmt) in enumerate(stats_rows):
        r = s0 + i
        ws.cell(row=r, column=2, value=label).font = HEADER_FONT
        for k, _ in enumerate(commodities):
            col = get_column_letter(3 + 5 * k + 4)
            rng = f"{col}{first}:{col}{last}"
            if formula is None:
                text = f"={col}{s0 + 2}/ABS({col}{s0 + 1})"
            else:
                text = "=" + formula.format(r=rng)
            ws.cell(row=r, column=3 + 5 * k + 4, value=text).number_format = fmt
    return s0 + len(stats_rows) + 2


def _surge_sheet(wb: Workbook, surge_blocks: dict[str, pd.DataFrame], commodities: list[str]) -> None:
    ws = wb.create_sheet("Surge")
    top = 1
    for title, wide in surge_blocks.items():
        top = _surge_block(ws, top, title, wide, commodities)
    ws.freeze_panes = "C3"
    _widths(ws, 13)


def _risk_sheet(wb: Workbook, draws: pd.DataFrame, commodities: list[str],
                qty_cells: dict[str, str], python_summary: pd.DataFrame, title: str) -> None:
    ws = wb.create_sheet("Risk")
    _title(ws, 1, title)
    n = len(draws)
    labels = ["Draw"]
    for c in commodities:
        labels += [f"{c} baseline", f"{c} surge", f"{c} price (formula)"]
    labels.append("Basket cost (formula)")
    _header(ws, 2, 1, labels)
    first, last = 3, 2 + n
    basket_col = 2 + 3 * len(commodities)
    for i in range(n):
        r = first + i
        ws.cell(row=r, column=1, value=i + 1)
        terms = []
        for k, c in enumerate(commodities):
            col = 2 + 3 * k
            ws.cell(row=r, column=col, value=round(float(draws.iat[i, 2 * k]), 4))
            ws.cell(row=r, column=col + 1, value=round(float(draws.iat[i, 2 * k + 1]), 6))
            b, s = get_column_letter(col), get_column_letter(col + 1)
            ws.cell(row=r, column=col + 2, value=f"={b}{r}*(1+{s}{r})")
            terms.append(f"{get_column_letter(col + 2)}{r}*{qty_cells[c]}")
        ws.cell(row=r, column=basket_col, value="=" + "+".join(terms))

    sc = basket_col + 2
    _header(ws, 2, sc, ["Measure", *commodities, "basket"])
    measures = [("Expected price (AVERAGE)", "AVERAGE({p})"),
                ("P5 price (PERCENTILE.INC)", "_xlfn.PERCENTILE.INC({p},0.05)"),
                ("P95 price (PERCENTILE.INC)", "_xlfn.PERCENTILE.INC({p},0.95)"),
                ("P(surge > 10%) (COUNTIF)", 'COUNTIF({s},">0.1")/COUNT({s})'),
                ("P(surge > 20%) (COUNTIF)", 'COUNTIF({s},">0.2")/COUNT({s})'),
                ("Price-at-risk = P95 - expected", "_xlfn.PERCENTILE.INC({p},0.95)-AVERAGE({p})")]
    for i, (label, formula) in enumerate(measures):
        r = 3 + i
        ws.cell(row=r, column=sc, value=label).font = HEADER_FONT
        for k, c in enumerate(commodities + ["basket"]):
            if c == "basket":
                p = f"{get_column_letter(basket_col)}{first}:{get_column_letter(basket_col)}{last}"
                if "{s}" in formula:
                    continue
                s = p
            else:
                pc = get_column_letter(2 + 3 * k + 2)
                scol = get_column_letter(2 + 3 * k + 1)
                p, s = f"{pc}{first}:{pc}{last}", f"{scol}{first}:{scol}{last}"
            cell = ws.cell(row=r, column=sc + 1 + k, value="=" + formula.format(p=p, s=s))
            cell.number_format = "0.0%" if "COUNTIF" in formula else "#,##0.00"
    r0 = 3 + len(measures) + 2
    ws.cell(row=r0, column=sc, value="Python values (notebook section 7) for comparison").font = HEADER_FONT
    _header(ws, r0 + 1, sc, ["Measure", *python_summary.columns])
    for i, (label, row) in enumerate(python_summary.iterrows()):
        ws.cell(row=r0 + 2 + i, column=sc, value=label)
        for j, v in enumerate(row):
            ws.cell(row=r0 + 2 + i, column=sc + 1 + j, value=None if pd.isna(v) else round(float(v), 6))
    ws.freeze_panes = "B3"
    _widths(ws, 13)


def _frame_sheet(wb: Workbook, name: str, title: str, frame: pd.DataFrame,
                 formulas: dict[str, str] | None = None, number_formats: dict[str, str] | None = None,
                 footer: list[tuple[str, str]] | None = None) -> None:
    """Write a frame; `formulas` maps new column -> template using {col_name} and {r}."""
    ws = wb.create_sheet(name)
    _title(ws, 1, title)
    cols = list(frame.columns) + list((formulas or {}).keys())
    _header(ws, 2, 1, cols)
    letter = {c: get_column_letter(i + 1) for i, c in enumerate(cols)}
    for i, (_, row) in enumerate(frame.iterrows()):
        r = 3 + i
        for j, c in enumerate(frame.columns):
            v = row[c]
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            elif pd.isna(v) if not isinstance(v, (list, tuple)) else False:
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            ws.cell(row=r, column=j + 1, value=v)
        for c, tmpl in (formulas or {}).items():
            ws.cell(row=r, column=cols.index(c) + 1, value="=" + tmpl.format(r=r, **letter))
    for c, fmt in (number_formats or {}).items():
        for r in range(3, 3 + len(frame)):
            ws.cell(row=r, column=cols.index(c) + 1).number_format = fmt
    last = 2 + len(frame)
    for i, (label, tmpl) in enumerate(footer or []):
        r = last + 2 + i
        ws.cell(row=r, column=1, value=label).font = HEADER_FONT
        ws.cell(row=r, column=2, value="=" + tmpl.format(first=3, last=last, **letter))
    _widths(ws, 15)


def build_workbook(path: Path, *, data: pd.DataFrame, flags: pd.Series,
                   surge_blocks: dict[str, pd.DataFrame], commodities: list[str],
                   draws: pd.DataFrame, risk_title: str, python_risk: pd.DataFrame,
                   scenarios: pd.DataFrame, backtest: pd.DataFrame,
                   assumptions: pd.DataFrame, basket: dict[str, float]) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    _data_sheet(wb, data, flags)
    _surge_sheet(wb, surge_blocks, commodities)

    # Assumptions first in memory so Risk formulas can point at the basket cells.
    qty_cells = {c: f"Assumptions!$C${3 + i}" for i, c in enumerate(commodities)}
    _risk_sheet(wb, draws, commodities, qty_cells, python_risk, risk_title)
    _frame_sheet(wb, "Scenarios", "Scenario results (Version A draws, common random numbers; computed in Python)",
                 scenarios)
    _frame_sheet(
        wb, "Backtest", "Rolling-origin backtest: APE and band coverage as live formulas",
        backtest,
        formulas={"APE (formula)": "ABS({forecast_median}{r}-{actual_price}{r})/{actual_price}{r}",
                  "Naive APE (formula)": "ABS({naive_last_price}{r}-{actual_price}{r})/{actual_price}{r}",
                  "Price in P5-P95 (formula)": "AND({actual_price}{r}>={forecast_p5}{r},{actual_price}{r}<={forecast_p95}{r})",
                  "Surge in P5-P95 (formula)": "AND({actual_surge}{r}>={surge_p5}{r},{actual_surge}{r}<={surge_p95}{r})"},
        footer=[("MAPE, model (AVERAGE)", "AVERAGE({APE (formula)}{first}:{APE (formula)}{last})"),
                ("MAPE, naive (AVERAGE)", "AVERAGE({Naive APE (formula)}{first}:{Naive APE (formula)}{last})"),
                ("Price coverage (COUNTIF)", 'COUNTIF({Price in P5-P95 (formula)}{first}:{Price in P5-P95 (formula)}{last},TRUE)/COUNTA({Price in P5-P95 (formula)}{first}:{Price in P5-P95 (formula)}{last})'),
                ("Surge coverage (COUNTIF)", 'COUNTIF({Surge in P5-P95 (formula)}{first}:{Surge in P5-P95 (formula)}{last},TRUE)/COUNTA({Surge in P5-P95 (formula)}{first}:{Surge in P5-P95 (formula)}{last})')])

    ws = wb.create_sheet("Assumptions")
    _title(ws, 1, "Assumptions (basket quantities in C3:C6 drive the Risk sheet formulas)")
    _header(ws, 2, 1, ["Item", "Commodity", "Value", "Unit / note"])
    for i, c in enumerate(commodities):
        ws.cell(row=3 + i, column=1, value="Monthly household basket quantity")
        ws.cell(row=3 + i, column=2, value=c)
        ws.cell(row=3 + i, column=3, value=float(basket[c]))
        ws.cell(row=3 + i, column=4, value="litre per month" if "oil" in c else "kg per month")
    for i, (_, row) in enumerate(assumptions.iterrows(), start=3 + len(commodities)):
        ws.cell(row=i, column=1, value=str(row["item"]))
        ws.cell(row=i, column=3, value=str(row["value"]))
        ws.cell(row=i, column=4, value=str(row["note"]))
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 30
    ws.column_dimensions["D"].width = 70

    order = ["Data", "Surge", "Risk", "Scenarios", "Backtest", "Assumptions"]
    wb._sheets = [wb[name] for name in order]  # noqa: SLF001 (openpyxl has no public reorder)
    path = Path(path)
    wb.save(path)
    return path
