# formats/xlsx.py
#
# Author: Patrick Beal
#
# Invoice as an Excel workbook, following docs/invoice-example/

from datetime import timedelta
from pathlib import Path

import pendulum

from timetracker.errors import TimeTrackerError
from timetracker.formats import header, range_label, total_row
from timetracker.invoice import InvoiceDocument, period_label
from timetracker.report import Report
from timetracker.user import address_lines, full_name

HEADERS = ("Date", "Project", "Hours", "Amount", "Description")

DATE_FORMAT = "M/d/yyyy"
HOURS_FORMAT = "[h]:mm:ss"  # counts past 24 hours instead of wrapping
MONEY_FORMAT = '"$"#,##0.00'


def render_xlsx(document: InvoiceDocument, path: Path):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font
    except ImportError:
        raise TimeTrackerError(
            "Excel output needs openpyxl. Reinstall the app with `uv sync`."
        ) from None

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Invoice"
    bold = Font(bold=True)

    title = f"HOURLY INVOICE\n{period_label(document)}"
    if document.predicted:
        title += "\n(DRAFT)"
    sheet["B1"] = title
    sheet["B1"].font = bold
    sheet["B1"].alignment = Alignment(wrap_text=True)
    sheet.merge_cells("B1:D1")
    sheet["E1"] = "INVOICE NUMBER:"
    sheet["F1"] = document.number

    sheet["B3"] = "From:"
    sheet["B3"].font = bold
    sheet["B4"] = full_name(document.user)
    for offset, line in enumerate(address_lines(document.user), start=5):
        sheet[f"B{offset}"] = line

    row_number = 5 + len(address_lines(document.user)) + 1
    sheet[f"B{row_number}"] = "Bill To:"
    sheet[f"B{row_number}"].font = bold
    row_number += 1
    sheet[f"B{row_number}"] = document.client_name

    row_number += 2
    for column, heading in zip("BCDEF", HEADERS):
        cell = sheet[f"{column}{row_number}"]
        cell.value = heading
        cell.font = bold

    for line in document.rows:
        row_number += 1
        sheet[f"B{row_number}"] = line.day
        sheet[f"B{row_number}"].number_format = DATE_FORMAT
        sheet[f"C{row_number}"] = line.project or ""
        sheet[f"D{row_number}"] = timedelta(seconds=line.seconds)
        sheet[f"D{row_number}"].number_format = HOURS_FORMAT
        if line.cents is not None:
            sheet[f"E{row_number}"] = line.cents / 100
            sheet[f"E{row_number}"].number_format = MONEY_FORMAT
        sheet[f"F{row_number}"] = line.description or ""
        sheet[f"F{row_number}"].alignment = Alignment(wrap_text=True, vertical="top")

    row_number += 1
    sheet[f"B{row_number}"] = "Total"
    sheet[f"D{row_number}"] = timedelta(seconds=document.total_seconds)
    sheet[f"D{row_number}"].number_format = HOURS_FORMAT
    if document.total_cents is not None:
        sheet[f"E{row_number}"] = document.total_cents / 100
        sheet[f"E{row_number}"].number_format = MONEY_FORMAT
    for column in "BCDEF":
        sheet[f"{column}{row_number}"].font = bold

    if document.user["payment_notes"]:
        row_number += 2
        sheet[f"B{row_number}"] = document.user["payment_notes"]

    for column, width in zip("BCDEF", (12, 18, 12, 12, 50)):
        sheet.column_dimensions[column].width = width

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


# --- Reports ---

REPORT_FORMATS = {
    "start": "M/d/yyyy h:mm:ss",
    "end": "M/d/yyyy h:mm:ss",
    "duration": HOURS_FORMAT,
    "rate": MONEY_FORMAT,
    "pay": MONEY_FORMAT,
}


def render_report_xlsx(report: Report, path: Path):
    """A report as a spreadsheet, with real dates, durations, and money."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise TimeTrackerError(
            "Excel output needs openpyxl. Reinstall the app with `uv sync`."
        ) from None

    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Report"
    bold = Font(bold=True)

    sheet["A1"] = "TIME REPORT"
    sheet["A1"].font = bold
    sheet["A2"] = range_label(report)

    header_row = 4
    for column, field in enumerate(report.fields, start=1):
        cell = sheet.cell(row=header_row, column=column, value=header(report, field))
        cell.font = bold

    for offset, row in enumerate(report.rows, start=1):
        _write_report_row(sheet, header_row + offset, report, row)

    total_line = header_row + len(report.rows) + 1
    _write_report_row(sheet, total_line, report, total_row(report))
    for column in range(1, len(report.fields) + 1):
        sheet.cell(row=total_line, column=column).font = bold

    for column, field in enumerate(report.fields, start=1):
        letter = get_column_letter(column)
        sheet.column_dimensions[letter].width = 60 if field == "description" else 20

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)


def _write_report_row(sheet, row_number: int, report: Report, row: dict):
    from openpyxl.styles import Alignment

    for column, field in enumerate(report.fields, start=1):
        cell = sheet.cell(row=row_number, column=column)
        cell.value = _xlsx_value(field, row[field])
        if row[field] is not None and field in REPORT_FORMATS:
            cell.number_format = REPORT_FORMATS[field]
        if field == "description":
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def _xlsx_value(field: str, value):
    """Numbers, dates, and durations stay typed so Excel can work with them."""
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if field in ("start", "end") and isinstance(value, int):
        return pendulum.from_timestamp(value, tz="local").naive()
    if field == "duration" and isinstance(value, int):
        return timedelta(seconds=value)
    if field == "pay" and isinstance(value, int):
        return value / 100
    return value
