# formats/table.py
#
# Author: Patrick Beal
#
# Terminal (Rich) and Markdown tables

from rich import box
from rich.table import Table

from timetracker.formats import header, text_value, total_row
from timetracker.report import Report

_RIGHT_ALIGNED = {"id", "duration", "rate", "pay"}

# Values that are unreadable when cut off. Names and descriptions wrap instead.
_NO_WRAP = {"start", "end", "duration", "rate", "pay"}


def render_table(report: Report) -> Table:
    """
    A styled terminal table. Rich wraps multi-line descriptions inside their
    cell, so the blank lines between appended descriptions are kept.
    """
    # No vertical borders, which leaves more room for columns
    table = Table(show_footer=True, box=box.SIMPLE_HEAD)
    total = total_row(report)
    for field in report.fields:
        table.add_column(
            header(report, field),
            footer=text_value(field, total[field]),
            justify="right" if field in _RIGHT_ALIGNED else "left",
            no_wrap=field in _NO_WRAP
            or (field == "period" and report.group_by == "day"),
            # Keeps names and descriptions readable when the terminal is narrow
            min_width=8 if field in ("client", "project", "description") else None,
        )
    for row in report.rows:
        table.add_row(*(_cell(f, row[f]) for f in report.fields))
    return table


def _cell(field: str, value) -> str:
    # Seconds on start/end crowd a terminal table. Duration keeps them.
    if field in ("start", "end") and value is not None:
        return text_value(field, value)[:-3]
    return text_value(field, value)


def render_markdown(report: Report) -> str:
    """
    A Markdown table. Newlines would end the row, so they become <br>, and
    pipes are escaped so they aren't read as column breaks.
    """
    lines = [
        _md_line(header(report, f) for f in report.fields),
        _md_line("---:" if f in _RIGHT_ALIGNED else "---" for f in report.fields),
    ]
    for row in [*report.rows, total_row(report)]:
        lines.append(_md_line(_md_cell(text_value(f, row[f])) for f in report.fields))
    return "\n".join(lines) + "\n"


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def _md_line(cells) -> str:
    return "| " + " | ".join(cells) + " |"
