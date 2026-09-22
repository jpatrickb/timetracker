# report.py
#
# Author: Patrick Beal
#
# Builds reports: filters entries, then lists them or groups them by period

import sqlite3 as sq
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pendulum

from timetracker.clock import DESCRIPTION_SEPARATOR
from timetracker.errors import TimeTrackerError

GroupBy = Literal["entry", "day", "week", "month"]
GROUP_BY_OPTIONS: tuple[GroupBy, ...] = ("entry", "day", "week", "month")

# Fields in display order. Grouped reports always lead with the period.
ENTRY_FIELDS = (
    "id",
    "start",
    "end",
    "client",
    "project",
    "description",
    "duration",
    "rate",
    "pay",
)
GROUPED_FIELDS = ("period", "id", "client", "project", "description", "duration", "pay")


@dataclass
class Report:
    """
    Raw report data. Values stay unformatted (epoch seconds, durations in
    seconds, pay in integer cents, lists for grouped IDs and names) so each
    output format can render them its own way.
    """

    group_by: GroupBy
    start: date | None
    end: date
    fields: list[str]
    rows: list[dict] = field(default_factory=list)
    # The matched entries themselves, which invoices link to
    entry_ids: list[int] = field(default_factory=list)
    client_ids: list[int] = field(default_factory=list)
    first_day: date | None = None
    total_seconds: int = 0
    total_cents: int | None = None
    skipped_open: int = 0


def parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise TimeTrackerError(f"Can't read date '{text}'. Use YYYY-MM-DD.") from None


def current_week() -> tuple[date, date]:
    """Monday through Sunday of this week, in local time."""
    monday = pendulum.today().start_of("week")
    return monday.date(), monday.add(days=6).date()


def build_report(
    conn: sq.Connection,
    clients: list[str] | None = None,
    projects: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    group_by: GroupBy = "entry",
    fields: list[str] | None = None,
    include_billed: bool = True,
) -> Report:
    """
    Collects finished entries that start within [start, end] (local dates,
    both inclusive) and match the client/project filters.

    With no dates the range is the current week. With only a start, it runs
    to today. With only an end, it has no lower bound. Entries belong to the
    range they start in, even if they run past its end.

    With include_billed False, entries already on an issued invoice are left
    out, which is what invoice generation uses to avoid double billing.
    """
    if start is None and end is None:
        start, end = current_week()
    elif end is None:
        end = pendulum.today().date()

    report = Report(
        group_by=group_by, start=start, end=end, fields=_check_fields(group_by, fields)
    )

    where, params = _filters(conn, clients, projects, start, end, include_billed)
    entries = conn.execute(
        f"""
        SELECT e.entry_id, e.start_time, e.end_time, e.duration, e.client_id,
            c.client_name, p.project_name, e.description,
            e.pay_rate_hourly, e.total_pay
        FROM time_entries AS e
        LEFT JOIN clients AS c ON c.client_id = e.client_id
        LEFT JOIN projects AS p ON p.project_id = e.project_id
        WHERE {where}
        ORDER BY e.start_time, e.entry_id
        """,
        params,
    ).fetchall()

    finished = [e for e in entries if e["end_time"] is not None]
    report.skipped_open = len(entries) - len(finished)
    report.entry_ids = [e["entry_id"] for e in finished]
    report.client_ids = list(dict.fromkeys(e["client_id"] for e in finished))
    if finished:
        report.first_day = pendulum.from_timestamp(
            finished[0]["start_time"], tz="local"
        ).date()

    if group_by == "entry":
        report.rows = [_entry_row(e) for e in finished]
    else:
        report.rows = _group(finished, group_by)

    report.total_seconds = sum(r["duration"] for r in report.rows)
    report.total_cents = sum_cents(r["pay"] for r in report.rows)
    return report


def _check_fields(group_by: GroupBy, fields: list[str] | None) -> list[str]:
    available = ENTRY_FIELDS if group_by == "entry" else GROUPED_FIELDS
    if not fields:
        return list(available)

    unknown = [f for f in fields if f not in available]
    if unknown:
        per_entry = [f for f in unknown if f in ENTRY_FIELDS]
        if group_by != "entry" and per_entry:
            raise TimeTrackerError(
                f"{', '.join(per_entry)} can't be shown when grouping by "
                f"{group_by}, only with --group-by entry. "
                f"Available: {', '.join(available)}."
            )
        raise TimeTrackerError(
            f"Unknown field(s): {', '.join(unknown)}. "
            f"Available: {', '.join(available)}."
        )

    # Grouped rows are meaningless without their period, so it's always first
    if group_by != "entry" and "period" not in fields:
        fields = ["period", *fields]
    return fields


def _filters(
    conn: sq.Connection,
    clients: list[str] | None,
    projects: list[str] | None,
    start: date | None,
    end: date,
    include_billed: bool = True,
) -> tuple[str, list]:
    """
    Builds the WHERE clause. Names are matched by name or alias. A name that
    doesn't match anything is ignored rather than an error, so a filter made
    only of unknown names returns nothing.
    """
    clauses = ["e.start_time < ?"]
    params: list = [_local_midnight(end, days_after=1)]
    if start is not None:
        clauses.append("e.start_time >= ?")
        params.append(_local_midnight(start))

    client_ids: list[int] = []
    if clients:
        client_ids = [
            row[0]
            for row in conn.execute(
                f"SELECT DISTINCT client_id FROM client_alias "
                f"WHERE client_alias_text IN ({_marks(clients)})",
                clients,
            )
        ]
        clauses.append(f"e.client_id IN ({_marks(client_ids)})")
        params.extend(client_ids)

    if projects:
        # A shared project name matches every client's project of that name,
        # narrowed to the --client filter if one was given
        query = (
            f"SELECT DISTINCT project_id FROM project_alias "
            f"WHERE project_alias_text IN ({_marks(projects)})"
        )
        query_params: list = list(projects)
        if clients:
            query += f" AND client_id IN ({_marks(client_ids)})"
            query_params.extend(client_ids)
        project_ids = [row[0] for row in conn.execute(query, query_params)]
        clauses.append(f"e.project_id IN ({_marks(project_ids)})")
        params.extend(project_ids)

    if not include_billed:
        clauses.append(
            """NOT EXISTS (
                SELECT 1 FROM invoice_entries AS ie
                JOIN invoices AS i ON i.invoice_id = ie.invoice_id
                WHERE ie.entry_id = e.entry_id AND i.status = 'issued'
            )"""
        )

    return " AND ".join(clauses), params


def _marks(values: list) -> str:
    """`?, ?, ?` placeholders for an IN clause. Empty lists match nothing."""
    return ", ".join("?" * len(values)) or "NULL"


def _local_midnight(day: date, days_after: int = 0) -> int:
    moment = pendulum.local(day.year, day.month, day.day).add(days=days_after)
    return moment.int_timestamp


# --- Rows ---


def to_cents(pay: float | None) -> int | None:
    return None if pay is None else round(pay * 100)


def sum_cents(values) -> int | None:
    """Sums pay in cents. None (no rate) only if nothing had a rate."""
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def _entry_row(e: sq.Row) -> dict:
    return {
        "id": e["entry_id"],
        "start": e["start_time"],
        "end": e["end_time"],
        "client": e["client_name"],
        "project": e["project_name"],
        "description": e["description"],
        "duration": e["duration"],
        "rate": e["pay_rate_hourly"],
        "pay": to_cents(e["total_pay"]),
    }


def _group(entries: list[sq.Row], group_by: GroupBy) -> list[dict]:
    """
    Splits each entry at local period boundaries (midnight for days), then
    totals the pieces per period. Periods with no work get no row.
    """
    groups: dict[date, dict] = {}
    for e in entries:
        pieces = split_periods(e["start_time"], e["end_time"], group_by)
        cents = to_cents(e["total_pay"])
        pay_pieces: list[int | None] = (
            [None] * len(pieces)
            if cents is None
            else list(allocate_cents(cents, [secs for _, secs in pieces]))
        )

        for (period_start, seconds), pay in zip(pieces, pay_pieces):
            group = groups.setdefault(
                period_start,
                {
                    "period": _period_label(period_start, group_by),
                    "period_start": period_start,
                    "id": [],
                    "client": [],
                    "project": [],
                    "description": [],
                    "duration": 0,
                    "pay": [],
                },
            )
            _add_unique(group["id"], e["entry_id"])
            _add_unique(group["client"], e["client_name"])
            _add_unique(group["project"], e["project_name"])
            _add_unique(group["description"], e["description"])
            group["duration"] += seconds
            group["pay"].append(pay)

    rows = [groups[key] for key in sorted(groups)]
    for row in rows:
        row["description"] = DESCRIPTION_SEPARATOR.join(row["description"]) or None
        row["pay"] = sum_cents(row["pay"])
    return rows


def _add_unique(items: list, value):
    if value is not None and value not in items:
        items.append(value)


def split_periods(start: int, end: int, group_by: GroupBy) -> list[tuple[date, int]]:
    """
    Breaks [start, end) into (period start date, seconds) pieces at local
    day/week/month boundaries. Working in local time handles 23- and 25-hour
    days around DST changes.
    """
    unit = group_by
    pieces = []
    cursor = start
    while True:
        period = pendulum.from_timestamp(cursor, tz="local").start_of(unit)
        boundary = period.add(**{f"{unit}s": 1}).int_timestamp
        piece_end = min(end, boundary)
        pieces.append((period.date(), piece_end - cursor))
        if piece_end >= end:
            return pieces
        cursor = piece_end


def allocate_cents(total_cents: int, seconds: list[int]) -> list[int]:
    """
    Divides an entry's pay across its pieces in proportion to time, in whole
    cents, so the pieces always add back up to the entry's exact total.
    Leftover cents go to the pieces that lost the most to rounding down.
    """
    duration = sum(seconds)
    if duration == 0:
        return [total_cents] + [0] * (len(seconds) - 1)

    exact = [total_cents * s / duration for s in seconds]
    shares = [int(x) for x in exact]
    leftover = total_cents - sum(shares)
    by_remainder = sorted(
        range(len(exact)), key=lambda i: exact[i] - shares[i], reverse=True
    )
    for i in by_remainder[:leftover]:
        shares[i] += 1
    return shares


def _period_label(period_start: date, group_by: GroupBy) -> str:
    if group_by == "day":
        return period_start.isoformat()
    if group_by == "week":
        first = pendulum.date(period_start.year, period_start.month, period_start.day)
        return f"{first.isoformat()} to {first.add(days=6).isoformat()}"
    return period_start.strftime("%Y-%m")
