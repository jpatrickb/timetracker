# formats/json_format.py
#
# Author: Patrick Beal
#
# JSON output (named json_format so it isn't confused with the json module)

import json

import pendulum

from timetracker.report import Report


def render_json(report: Report) -> str:
    """
    Machine-readable output: times as ISO 8601 with the local UTC offset,
    durations in whole seconds, money as numbers in dollars, and grouped
    IDs/clients/projects as arrays.
    """
    data = {
        "group_by": report.group_by,
        "start": report.start.isoformat() if report.start else None,
        "end": report.end.isoformat(),
        "rows": [
            {f: _json_value(f, row[f]) for f in report.fields} for row in report.rows
        ],
        "totals": {
            "duration": report.total_seconds,
            "pay": _json_value("pay", report.total_cents),
        },
        "skipped_open_entries": report.skipped_open,
    }
    return json.dumps(data, indent=2) + "\n"


def _json_value(field: str, value):
    if value is None:
        return None
    if field in ("start", "end"):
        return pendulum.from_timestamp(value, tz="local").isoformat()
    if field == "pay":
        return value / 100
    return value
