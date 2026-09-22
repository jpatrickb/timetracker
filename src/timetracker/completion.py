# completion.py
#
# Author: Patrick Beal
#
# Tab-completion for values that live in the database: client and project
# names, open entries, invoices

import sqlite3 as sq
from contextlib import contextmanager

import typer

from timetracker import db

# Completions run on every Tab press, so they open the database read-only:
# no migrations, no directory creation, and no chance of a write.
READ_ONLY = "file:{path}?mode=ro"


@contextmanager
def _reading():
    """
    Yields a read-only connection, or None if there's no database yet.
    Completion must never raise: a traceback in the middle of typing is worse
    than no suggestions.
    """
    path = db.resolve_db_path()
    if not path.exists():
        yield None
        return

    conn = None
    try:
        conn = sq.connect(READ_ONLY.format(path=path), uri=True)
        conn.row_factory = sq.Row
        yield conn
    except sq.Error:
        yield None
    finally:
        if conn is not None:
            conn.close()


def _rows(query: str, params: tuple = ()) -> list[sq.Row]:
    with _reading() as conn:
        if conn is None:
            return []
        try:
            return conn.execute(query, params).fetchall()
        except sq.Error:
            return []


def _matching(values, incomplete: str):
    """Keeps the suggestions that start with what's been typed, ignoring case."""
    return [v for v in values if str(v[0]).lower().startswith(incomplete.lower())]


# --- Clients and projects ---


def clients(incomplete: str) -> list[tuple[str, str]]:
    rows = _rows(
        """
        SELECT a.client_alias_text AS name, c.client_name
        FROM client_alias AS a
        JOIN clients AS c ON c.client_id = a.client_id
        ORDER BY a.client_alias_text
        """
    )
    # An alias shows the full client name as its help text
    return _matching(
        [
            (r["name"], "" if r["name"] == r["client_name"] else r["client_name"])
            for r in rows
        ],
        incomplete,
    )


def projects(ctx: typer.Context, incomplete: str) -> list[tuple[str, str]]:
    """Projects, narrowed to --client (or the client argument) when given."""
    client = ctx.params.get("client")
    query = """
        SELECT a.project_alias_text AS name, c.client_name
        FROM project_alias AS a
        JOIN clients AS c ON c.client_id = a.client_id
        WHERE (? IS NULL OR c.client_id = (
            SELECT client_id FROM client_alias WHERE client_alias_text = ?
        ))
        ORDER BY a.project_alias_text
    """
    rows = _rows(query, (client, client))
    return _matching([(r["name"], r["client_name"]) for r in rows], incomplete)


# --- Entries ---


def _entry_choices(where: str) -> list[tuple[str, str]]:
    rows = _rows(
        f"""
        SELECT e.entry_id, e.start_time, c.client_name, p.project_name
        FROM time_entries AS e
        LEFT JOIN clients AS c ON c.client_id = e.client_id
        LEFT JOIN projects AS p ON p.project_id = e.project_id
        WHERE {where}
        ORDER BY e.start_time DESC
        LIMIT 25
        """
    )

    from timetracker.clock import format_timestamp

    choices = []
    for row in rows:
        parts = [p for p in (row["client_name"], row["project_name"]) if p]
        label = "/".join(parts) or "no client"
        choices.append(
            (str(row["entry_id"]), f"{label}, {format_timestamp(row['start_time'])}")
        )
    return choices


def open_entries(incomplete: str) -> list[tuple[str, str]]:
    return _matching(_entry_choices("e.end_time IS NULL"), incomplete)


def entries(incomplete: str) -> list[tuple[str, str]]:
    """Recent entries, newest first, for edit and delete."""
    return _matching(_entry_choices("1 = 1"), incomplete)


# --- Invoices ---


def _invoice_choices(statuses: tuple[str, ...]) -> list[tuple[str, str]]:
    marks = ", ".join("?" * len(statuses))
    rows = _rows(
        f"""
        SELECT i.invoice_id, i.invoice_number, i.status, i.period_start, i.period_end,
            c.client_name
        FROM invoices AS i
        JOIN clients AS c ON c.client_id = i.client_id
        WHERE i.status IN ({marks})
        ORDER BY i.invoice_id DESC
        """,
        statuses,
    )
    return [
        (
            str(r["invoice_id"]),
            f"{r['client_name']}, {r['period_start']} to {r['period_end']}"
            + (f", #{r['invoice_number']}" if r["invoice_number"] else " (draft)"),
        )
        for r in rows
    ]


def draft_invoices(incomplete: str) -> list[tuple[str, str]]:
    return _matching(_invoice_choices(("draft",)), incomplete)


def issued_invoices(incomplete: str) -> list[tuple[str, str]]:
    return _matching(_invoice_choices(("issued",)), incomplete)


def any_invoices(incomplete: str) -> list[tuple[str, str]]:
    return _matching(_invoice_choices(("draft", "issued", "void")), incomplete)


# --- Report options ---


def report_fields(incomplete: str) -> list[str]:
    """--fields takes a comma-separated list, so only the last name completes."""
    from timetracker.report import ENTRY_FIELDS, GROUPED_FIELDS

    prefix, _, typing = incomplete.rpartition(",")
    chosen = {name.strip() for name in prefix.split(",")}
    available = dict.fromkeys((*ENTRY_FIELDS, *GROUPED_FIELDS))

    head = f"{prefix}," if prefix else ""
    return [
        f"{head}{name}"
        for name in available
        if name not in chosen and name.startswith(typing.strip())
    ]
