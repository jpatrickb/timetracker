# formats/delimited.py
#
# Author: Patrick Beal
#
# CSV and TSV output

import csv
import io

from timetracker.formats import header, text_value
from timetracker.report import Report


def render_csv(report: Report) -> str:
    """
    CSV with numbers left plain for spreadsheets. Descriptions keep their
    newlines: the csv module quotes those cells, which spreadsheet apps read
    as multi-line cells.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header(report, f) for f in report.fields)
    for row in report.rows:
        writer.writerow(text_value(f, row[f], plain=True) for f in report.fields)
    return out.getvalue()


def render_tsv(report: Report) -> str:
    """
    TSV has no quoting, so tabs and newlines inside a value are escaped as
    \\t and \\n (the convention tools like PostgreSQL use). Every line is
    then exactly one row.
    """
    lines = ["\t".join(header(report, f) for f in report.fields)]
    for row in report.rows:
        lines.append(
            "\t".join(_escape(text_value(f, row[f], plain=True)) for f in report.fields)
        )
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")
