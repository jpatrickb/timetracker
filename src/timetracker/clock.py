# clock.py
#
# Author: Patrick Beal
#
# Time entries: clocking in and out, manual entries, edits, and deletes

import re
import sqlite3 as sq
from collections.abc import Callable

import pendulum
from pendulum import DateTime

from timetracker import clients
from timetracker.errors import TimeTrackerError

# Goes between the old and new description when clocking out with --desc
DESCRIPTION_SEPARATOR = "\n\n"

# HH:MM or HH:MM:SS, optionally preceded by YYYY-MM-DD and a space or T
_TIME_PATTERN = re.compile(
    r"(?:(\d{4})-(\d{2})-(\d{2})[ T])?(\d{1,2}):(\d{2})(?::(\d{2}))?"
)

# Every entry query goes through this so rows always carry client/project names
_ENTRY_QUERY = """
    SELECT e.entry_id, e.start_time, e.end_time, e.duration,
        e.client_id, c.client_name, e.project_id, p.project_name,
        e.description, e.pay_rate_hourly, e.total_pay
    FROM time_entries AS e
    LEFT JOIN clients AS c ON c.client_id = e.client_id
    LEFT JOIN projects AS p ON p.project_id = e.project_id
"""


# --- Time helpers ---


def parse_time(text: str, warn: Callable[[str], None] | None = None) -> DateTime:
    """
    Reads a user-typed time in the machine's local time zone. Accepts HH:MM,
    HH:MM:SS, or either one after a YYYY-MM-DD date. Without a date, today is
    assumed.

    On daylight saving changes a local time can be missing (clocks spring
    forward) or happen twice (clocks fall back). Those are resolved to the
    later real time and the first occurrence respectively, and `warn` is
    called with a message saying which time was used.
    """
    match = _TIME_PATTERN.fullmatch(text.strip())
    if not match:
        raise TimeTrackerError(
            f"Can't read time '{text}'. Use HH:MM, HH:MM:SS, or 'YYYY-MM-DD HH:MM'."
        )

    year, month, day, hour, minute, second = match.groups()
    today = pendulum.today()
    parts = (
        int(year) if year else today.year,
        int(month) if month else today.month,
        int(day) if day else today.day,
        int(hour),
        int(minute),
        int(second or 0),
    )

    # fold picks between the two readings of an ambiguous or missing time
    tz = pendulum.local_timezone()
    try:
        first = pendulum.datetime(*parts, tz=tz, fold=0)
        later = pendulum.datetime(*parts, tz=tz, fold=1)
    except ValueError as e:
        raise TimeTrackerError(f"Invalid time '{text}': {e}") from None

    if first.utcoffset() == later.utcoffset():
        return first

    typed = f"{parts[3]:02}:{parts[4]:02}"
    date = f"{parts[0]}-{parts[1]:02}-{parts[2]:02}"
    if (first.hour, first.minute) != parts[3:5]:
        result = later
        message = (
            f"{typed} doesn't exist on {date} (clocks sprang forward). "
            f"Using {result.format('HH:mm zz')}."
        )
    else:
        result = first
        message = (
            f"{typed} happens twice on {date} (clocks fell back). "
            f"Using the first one, {result.format('HH:mm zz')}."
        )
    if warn:
        warn(message)
    return result


def now() -> int:
    """The current time as UTC epoch seconds."""
    return pendulum.now().int_timestamp


def format_timestamp(ts: int) -> str:
    """Epoch seconds as local time, e.g. 2026-09-22 09:14:05."""
    return pendulum.from_timestamp(ts, tz="local").format("YYYY-MM-DD HH:mm:ss")


def format_duration(seconds: int) -> str:
    """Seconds as H:MM:SS, e.g. 4:53:12. Hours keep counting past 24."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}"


def _check_times(start: int, end: int | None, current: int):
    if start > current:
        _future_error("Start time", start)
    if end is not None:
        if end > current:
            _future_error("End time", end)
        if end < start:
            raise TimeTrackerError(
                f"End time {format_timestamp(end)} is before start time "
                f"{format_timestamp(start)}."
            )


def _future_error(label: str, ts: int):
    message = f"{label} {format_timestamp(ts)} is in the future."

    # A time typed without a date means today, so a late-night time typed
    # just after midnight lands in the future. Suggest the dated form.
    moment = pendulum.from_timestamp(ts, tz="local")
    if moment.date() == pendulum.today().date():
        yesterday = moment.subtract(days=1).format("YYYY-MM-DD HH:mm")
        message += f" If you meant yesterday, include the date: '{yesterday}'."

    raise TimeTrackerError(message)


# --- Lookups ---


def get_entry(conn: sq.Connection, entry_id: int) -> sq.Row:
    row = conn.execute(_ENTRY_QUERY + " WHERE e.entry_id = ?", (entry_id,)).fetchone()
    if row is None:
        raise TimeTrackerError(f"No entry with ID {entry_id}.")
    return row


def open_entries(conn: sq.Connection) -> list[sq.Row]:
    """Entries that are clocked in but not yet out, oldest first."""
    return conn.execute(
        _ENTRY_QUERY + " WHERE e.end_time IS NULL ORDER BY e.start_time"
    ).fetchall()


def find_overlaps(
    conn: sq.Connection, start: int, end: int | None, exclude_id: int | None = None
) -> list[sq.Row]:
    """
    Entries whose time range overlaps [start, end). An open entry (no end)
    runs indefinitely, so two open entries always overlap. Back-to-back
    entries (one ends as the next starts) don't.
    """
    return conn.execute(
        _ENTRY_QUERY
        + """
        WHERE e.entry_id IS NOT ?
          AND (? IS NULL OR e.start_time < ?)
          AND (e.end_time IS NULL OR e.end_time > ?)
        ORDER BY e.start_time
        """,
        (exclude_id, end, end, start),
    ).fetchall()


def issued_invoice(conn: sq.Connection, entry_id: int) -> sq.Row | None:
    """The issued invoice an entry is billed on, if any."""
    return conn.execute(
        """
        SELECT i.invoice_number, c.client_name
        FROM invoice_entries AS ie
        JOIN invoices AS i ON i.invoice_id = ie.invoice_id
        JOIN clients AS c ON c.client_id = i.client_id
        WHERE ie.entry_id = ? AND i.status = 'issued'
        """,
        (entry_id,),
    ).fetchone()


def invoice_links(conn: sq.Connection, entry_id: int) -> list[sq.Row]:
    """Every invoice (draft, issued, or void) an entry is linked to."""
    return conn.execute(
        """
        SELECT i.invoice_id, i.status
        FROM invoice_entries AS ie
        JOIN invoices AS i ON i.invoice_id = ie.invoice_id
        WHERE ie.entry_id = ?
        """,
        (entry_id,),
    ).fetchall()


def _check_not_billed(conn: sq.Connection, entry_id: int, action: str):
    invoice = issued_invoice(conn, entry_id)
    if invoice:
        raise TimeTrackerError(
            f"Entry {entry_id} is billed on issued invoice #{invoice['invoice_number']} "
            f"for {invoice['client_name']}. Void that invoice before you {action} it."
        )


# --- Client, project, and rate ---


def _project_client(conn: sq.Connection, project_id: int) -> int:
    return conn.execute(
        "SELECT client_id FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()[0]


def _assignment(
    conn: sq.Connection,
    client: str | None,
    project: str | None,
    current_client_id: int | None = None,
    current_project_id: int | None = None,
) -> tuple[int | None, int | None]:
    """
    Works out an entry's (client_id, project_id) from --client and --project,
    starting from its current values.

    A project alone implies its client, and must be unambiguous across all
    clients. A new client without a new project drops the old project if it
    belonged to the old client.
    """
    if project:
        client_id = clients.resolve_client(conn, client)
        project_id = clients.resolve_project(conn, project, client_id)
        assert project_id is not None
        return _project_client(conn, project_id), project_id

    if client:
        client_id = clients.resolve_client(conn, client)
        project_id = current_project_id
        if project_id is not None and _project_client(conn, project_id) != client_id:
            project_id = None
        return client_id, project_id

    return current_client_id, current_project_id


def get_pay_rate(
    conn: sq.Connection, client_id: int | None, project_id: int | None
) -> float | None:
    """The project's rate if there's a project, otherwise the client's."""
    if project_id is not None:
        return conn.execute(
            "SELECT pay_rate_hourly FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
    if client_id is not None:
        return conn.execute(
            "SELECT pay_rate_hourly FROM clients WHERE client_id = ?", (client_id,)
        ).fetchone()[0]
    return None


# --- Commands ---


def clock_in(
    conn: sq.Connection,
    start: DateTime | None = None,
    client: str | None = None,
    project: str | None = None,
    description: str | None = None,
) -> tuple[int, list[sq.Row]]:
    """
    Opens a new entry. Returns its ID and any entries it overlaps, which
    includes anything still clocked in. Overlaps are allowed, the caller
    just warns about them.

    The pay rate stored now is provisional. It's looked up again at clock-out.
    """
    current = now()
    start_ts = start.int_timestamp if start else current
    _check_times(start_ts, None, current)

    client_id, project_id = _assignment(conn, client, project)
    overlaps = find_overlaps(conn, start_ts, None)

    entry_id = _insert(conn, start_ts, None, client_id, project_id, description)
    return entry_id, overlaps


def add_entry(
    conn: sq.Connection,
    start: DateTime,
    end: DateTime,
    client: str | None = None,
    project: str | None = None,
    description: str | None = None,
) -> tuple[int, list[sq.Row]]:
    """Logs a finished entry in one step. Returns its ID and any overlaps."""
    _check_times(start.int_timestamp, end.int_timestamp, now())

    client_id, project_id = _assignment(conn, client, project)
    overlaps = find_overlaps(conn, start.int_timestamp, end.int_timestamp)

    entry_id = _insert(
        conn, start.int_timestamp, end.int_timestamp, client_id, project_id, description
    )
    return entry_id, overlaps


def clock_out(
    conn: sq.Connection,
    entry_id: int,
    end: DateTime | None = None,
    client: str | None = None,
    project: str | None = None,
    description: str | None = None,
) -> list[sq.Row]:
    """
    Closes an open entry. A new client or project replaces the old one, and
    a description is appended to the existing one rather than replacing it.
    The pay rate is looked up at this point, so a rate set while the entry
    was open applies. Returns any entries the finished entry overlaps.
    """
    entry = get_entry(conn, entry_id)
    if entry["end_time"] is not None:
        raise TimeTrackerError(
            f"Entry {entry_id} is already clocked out. "
            f"Use `tt edit {entry_id} --end-time` to change it."
        )
    _check_not_billed(conn, entry_id, "clock out of")

    current = now()
    end_ts = end.int_timestamp if end else current
    _check_times(entry["start_time"], end_ts, current)

    client_id, project_id = _assignment(
        conn, client, project, entry["client_id"], entry["project_id"]
    )

    if description and entry["description"]:
        description = entry["description"] + DESCRIPTION_SEPARATOR + description

    _write(
        conn,
        entry_id,
        start_time=entry["start_time"],
        end_time=end_ts,
        client_id=client_id,
        project_id=project_id,
        description=description or entry["description"],
        pay_rate=get_pay_rate(conn, client_id, project_id),
    )
    return find_overlaps(conn, entry["start_time"], end_ts, exclude_id=entry_id)


def edit_entry(
    conn: sq.Connection,
    entry_id: int,
    start: DateTime | None = None,
    end: DateTime | None = None,
    client: str | None = None,
    project: str | None = None,
    description: str | None = None,
    *,
    clear_client: bool = False,
    clear_project: bool = False,
    clear_description: bool = False,
    reopen: bool = False,
    refresh_rate: bool = False,
) -> list[sq.Row]:
    """
    Corrects an entry. Unlike clock_out, a description replaces the old one.
    Entries on an issued invoice can't be edited.

    The pay rate is looked up again when the client or project changes, when
    the edit closes an open entry, or when refresh_rate is set. Otherwise the
    entry keeps its rate.

    Returns any overlaps, but only when the edit changed the entry's times.
    """
    if clear_client and (client or project):
        raise TimeTrackerError(
            "--no-client can't be combined with --client or --project."
        )
    if clear_project and project:
        raise TimeTrackerError("--no-project can't be combined with --project.")
    if clear_description and description is not None:
        raise TimeTrackerError("--no-desc can't be combined with --desc.")
    if reopen and end:
        raise TimeTrackerError("--reopen can't be combined with --end-time.")

    entry = get_entry(conn, entry_id)
    _check_not_billed(conn, entry_id, "edit")

    if reopen:
        if entry["end_time"] is None:
            raise TimeTrackerError(f"Entry {entry_id} is already open.")
        if invoice_links(conn, entry_id):
            raise TimeTrackerError(
                f"Entry {entry_id} is on a draft invoice, which needs a finished "
                "entry. Delete the draft before reopening it."
            )

    start_ts = start.int_timestamp if start else entry["start_time"]
    if reopen:
        end_ts = None
    else:
        end_ts = end.int_timestamp if end else entry["end_time"]
    _check_times(start_ts, end_ts, now())

    if clear_client:
        client_id, project_id = None, None
    else:
        client_id, project_id = _assignment(
            conn, client, project, entry["client_id"], entry["project_id"]
        )
    if clear_project:
        project_id = None

    closing = entry["end_time"] is None and end_ts is not None
    reassigned = (client_id, project_id) != (entry["client_id"], entry["project_id"])
    if refresh_rate or closing or reassigned:
        pay_rate = get_pay_rate(conn, client_id, project_id)
    else:
        pay_rate = entry["pay_rate_hourly"]

    if clear_description:
        new_description = None
    elif description is not None:
        new_description = description
    else:
        new_description = entry["description"]

    _write(
        conn,
        entry_id,
        start_time=start_ts,
        end_time=end_ts,
        client_id=client_id,
        project_id=project_id,
        description=new_description,
        pay_rate=pay_rate,
    )

    if (start_ts, end_ts) == (entry["start_time"], entry["end_time"]):
        return []
    return find_overlaps(conn, start_ts, end_ts, exclude_id=entry_id)


def delete_entry(conn: sq.Connection, entry_id: int):
    """
    Deletes an entry. Blocked if it's on an issued invoice, since that would
    change an invoice that was already sent. Links to drafts are removed.
    """
    get_entry(conn, entry_id)
    _check_not_billed(conn, entry_id, "delete")
    with conn:
        conn.execute("DELETE FROM time_entries WHERE entry_id = ?", (entry_id,))


# --- Writes ---


def _insert(
    conn: sq.Connection,
    start_time: int,
    end_time: int | None,
    client_id: int | None,
    project_id: int | None,
    description: str | None,
) -> int:
    with conn:
        entry_id = conn.execute(
            """
            INSERT INTO time_entries
                (start_time, end_time, client_id, project_id, description, pay_rate_hourly)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                start_time,
                end_time,
                client_id,
                project_id,
                description,
                get_pay_rate(conn, client_id, project_id),
            ),
        ).lastrowid
    assert entry_id is not None
    return entry_id


def _write(
    conn: sq.Connection,
    entry_id: int,
    *,
    start_time: int,
    end_time: int | None,
    client_id: int | None,
    project_id: int | None,
    description: str | None,
    pay_rate: float | None,
):
    """Overwrites every editable column of an entry with the given values."""
    with conn:
        conn.execute(
            """
            UPDATE time_entries
            SET start_time = ?, end_time = ?, client_id = ?, project_id = ?,
                description = ?, pay_rate_hourly = ?
            WHERE entry_id = ?
            """,
            (
                start_time,
                end_time,
                client_id,
                project_id,
                description,
                pay_rate,
                entry_id,
            ),
        )
