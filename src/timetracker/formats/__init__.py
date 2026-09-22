# formats/__init__.py
#
# Author: Patrick Beal
#
# Helpers shared by every report output format

from timetracker.clock import format_duration, format_timestamp
from timetracker.report import Report

_HEADERS = {
    "period": "Period",
    "id": "ID",
    "start": "Start",
    "end": "End",
    "client": "Client",
    "project": "Project",
    "description": "Description",
    "duration": "Duration",
    "rate": "Rate",
    "pay": "Pay",
}

# Grouped rows hold lists, so their headers are plural
_GROUPED_HEADERS = {"id": "Entries", "client": "Clients", "project": "Projects"}


def header(report: Report, field: str) -> str:
    if report.group_by != "entry" and field in _GROUPED_HEADERS:
        return _GROUPED_HEADERS[field]
    return _HEADERS[field]


def text_value(field: str, value, plain: bool = False) -> str:
    """
    Renders one report value as text. `plain` drops currency symbols and
    thousands separators so spreadsheets read numbers as numbers.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if field in ("start", "end"):
        return format_timestamp(value)
    if field == "duration":
        return format_duration(value)
    if field == "pay":
        return f"{value / 100:.2f}" if plain else f"${value / 100:,.2f}"
    if field == "rate":
        return f"{value:.2f}" if plain else f"${value:,.2f}"
    return str(value)


def total_row(report: Report) -> dict:
    """A row labeling the first column 'Total' with the summed duration and pay."""
    row: dict = {f: None for f in report.fields}
    row[report.fields[0]] = "Total"
    row["duration"] = report.total_seconds
    row["pay"] = report.total_cents
    return row


def range_label(report: Report) -> str:
    """e.g. '2026-09-21 to 2026-09-27, by day'."""
    start = report.start.isoformat() if report.start else "the beginning"
    return f"{start} to {report.end.isoformat()}, by {report.group_by}"


def default_filename(report: Report, extension: str) -> str:
    """e.g. report-2026-09-21-to-2026-09-27-by-day.csv"""
    start = report.start.isoformat() if report.start else "beginning"
    return (
        f"report-{start}-to-{report.end.isoformat()}-by-{report.group_by}.{extension}"
    )
