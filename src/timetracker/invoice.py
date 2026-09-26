# invoice.py
#
# Author: Patrick Beal
#
# Invoice lifecycle: drafts, issuing, voiding, and the data a rendered
# invoice is built from

import re
import sqlite3 as sq
from dataclasses import dataclass
from datetime import date

from timetracker import report, user
from timetracker.clock import DESCRIPTION_SEPARATOR
from timetracker.errors import TimeTrackerError


@dataclass
class InvoiceRow:
    """One line item: a day's work on one project."""

    day: date
    project: str | None
    seconds: int
    cents: int | None
    description: str | None
    # The hourly rate behind `cents`, so a renderer can show the arithmetic.
    # None when the row's entries were billed at differing rates.
    rate: float | None = None


@dataclass
class InvoiceDocument:
    """Everything a renderer needs. Rows are ordered by day, then project."""

    invoice_id: int
    number: int
    predicted: bool  # True while the invoice is still a draft
    status: str
    client_name: str
    user: sq.Row
    period_start: date
    period_end: date
    rows: list[InvoiceRow]
    total_seconds: int
    total_cents: int | None


# --- Lifecycle ---


def next_number(conn: sq.Connection, client_id: int) -> int:
    """
    One more than the highest number this client has used. Void invoices keep
    their number, so a client's printed sequence never repeats or skips.
    """
    highest = conn.execute(
        "SELECT MAX(invoice_number) FROM invoices WHERE client_id = ?", (client_id,)
    ).fetchone()[0]
    return (highest or 0) + 1


def create_draft(
    conn: sq.Connection,
    client_id: int,
    period_start: date,
    period_end: date,
    entry_ids: list[int],
) -> int:
    """
    Creates a draft invoice and links the given entries. A draft holds no
    number and bills nothing, so it can be made and thrown away freely.
    """
    if not entry_ids:
        raise TimeTrackerError("No entries to invoice for that selection.")

    with conn:
        invoice_id = conn.execute(
            """
            INSERT INTO invoices (client_id, date_generated, period_start, period_end,
                status)
            VALUES (?, unixepoch(), ?, ?, 'draft')
            """,
            (client_id, period_start.isoformat(), period_end.isoformat()),
        ).lastrowid
        assert invoice_id is not None

        for entry_id in entry_ids:
            try:
                conn.execute(
                    "INSERT INTO invoice_entries (invoice_id, entry_id) VALUES (?, ?)",
                    (invoice_id, entry_id),
                )
            except sq.IntegrityError as e:
                # The triggers enforce same client, finished entries, drafts only
                raise TimeTrackerError(f"Entry {entry_id}: {e}") from None

    return invoice_id


def issue(conn: sq.Connection, invoice_id: int) -> int:
    """
    Turns a draft into an issued invoice, allocating its number. Its entries
    count as billed from this point. Returns the allocated number.
    """
    invoice = _get(conn, invoice_id)
    if invoice["status"] != "draft":
        raise TimeTrackerError(
            f"Invoice {invoice_id} is already {invoice['status']}, not a draft."
        )

    number = next_number(conn, invoice["client_id"])
    try:
        with conn:
            conn.execute(
                "UPDATE invoices SET status = 'issued', invoice_number = ? "
                "WHERE invoice_id = ?",
                (number, invoice_id),
            )
    except sq.IntegrityError:
        # The double-billing trigger fired: name the entries that clash
        clashes = conn.execute(
            """
            SELECT mine.entry_id, other_invoice.invoice_number
            FROM invoice_entries AS mine
            JOIN invoice_entries AS other
                ON other.entry_id = mine.entry_id AND other.invoice_id <> mine.invoice_id
            JOIN invoices AS other_invoice ON other_invoice.invoice_id = other.invoice_id
            WHERE mine.invoice_id = ? AND other_invoice.status = 'issued'
            """,
            (invoice_id,),
        ).fetchall()
        listed = ", ".join(
            f"{r['entry_id']} (on #{r['invoice_number']})" for r in clashes
        )
        raise TimeTrackerError(
            f"Can't issue invoice {invoice_id}: already billed on another issued "
            f"invoice: entry {listed}. Void that invoice or remove the entries."
        ) from None

    return number


def void(conn: sq.Connection, invoice_id: int):
    """
    Voids an issued invoice. Its entries become billable again, and it keeps
    its number so the client's sequence stays gapless.
    """
    invoice = _get(conn, invoice_id)
    if invoice["status"] != "issued":
        raise TimeTrackerError(
            f"Only issued invoices can be voided. Invoice {invoice_id} is "
            f"{invoice['status']}."
        )
    with conn:
        conn.execute(
            "UPDATE invoices SET status = 'void' WHERE invoice_id = ?", (invoice_id,)
        )


def delete_draft(conn: sq.Connection, invoice_id: int):
    """Deletes a draft. Issued and void invoices are kept as a record."""
    invoice = _get(conn, invoice_id)
    if invoice["status"] != "draft":
        raise TimeTrackerError(
            f"Only drafts can be deleted. Invoice {invoice_id} is "
            f"{invoice['status']}, so void it instead."
        )
    with conn:
        conn.execute("DELETE FROM invoices WHERE invoice_id = ?", (invoice_id,))


def _get(conn: sq.Connection, invoice_id: int) -> sq.Row:
    invoice = conn.execute(
        "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    if invoice is None:
        raise TimeTrackerError(f"No invoice with ID {invoice_id}.")
    return invoice


def list_invoices(conn: sq.Connection) -> list[dict]:
    """Every invoice with its client, period, totals, and number (predicted for drafts)."""
    rows = conn.execute(
        """
        SELECT i.invoice_id, i.invoice_number, i.status, i.period_start, i.period_end,
            i.client_id, c.client_name,
            COALESCE(SUM(e.duration), 0) AS seconds,
            SUM(e.total_pay) AS pay
        FROM invoices AS i
        JOIN clients AS c ON c.client_id = i.client_id
        LEFT JOIN invoice_entries AS ie ON ie.invoice_id = i.invoice_id
        LEFT JOIN time_entries AS e ON e.entry_id = ie.entry_id
        GROUP BY i.invoice_id
        ORDER BY i.invoice_id
        """
    ).fetchall()

    listed = []
    for row in rows:
        data = dict(row)
        data["predicted"] = row["invoice_number"] is None
        if data["predicted"]:
            data["invoice_number"] = next_number(conn, row["client_id"])
        data["cents"] = report.to_cents(row["pay"])
        listed.append(data)
    return listed


# --- Document ---


def build_document(conn: sq.Connection, invoice_id: int) -> InvoiceDocument:
    """
    Reads an invoice's entries through invoice_entries rather than re-running
    the filters that made it, so a regenerated invoice always matches the one
    that was issued.
    """
    invoice = _get(conn, invoice_id)
    client_name = conn.execute(
        "SELECT client_name FROM clients WHERE client_id = ?", (invoice["client_id"],)
    ).fetchone()[0]

    entries = conn.execute(
        """
        SELECT e.start_time, e.end_time, e.description, e.total_pay,
            e.pay_rate_hourly, p.project_name
        FROM invoice_entries AS ie
        JOIN time_entries AS e ON e.entry_id = ie.entry_id
        LEFT JOIN projects AS p ON p.project_id = e.project_id
        WHERE ie.invoice_id = ?
        ORDER BY e.start_time, e.entry_id
        """,
        (invoice_id,),
    ).fetchall()

    rows = _line_items(entries)
    number = invoice["invoice_number"]
    predicted = number is None

    return InvoiceDocument(
        invoice_id=invoice_id,
        number=next_number(conn, invoice["client_id"]) if predicted else number,
        predicted=predicted,
        status=invoice["status"],
        client_name=client_name,
        user=user.require_user(conn),
        period_start=date.fromisoformat(invoice["period_start"]),
        period_end=date.fromisoformat(invoice["period_end"]),
        rows=rows,
        total_seconds=sum(r.seconds for r in rows),
        total_cents=report.sum_cents(r.cents for r in rows),
    )


def _line_items(entries: list[sq.Row]) -> list[InvoiceRow]:
    """
    One row per project per day. Sessions crossing midnight are split, with
    their pay divided in proportion so the rows still add up to the entries'
    exact totals.
    """
    groups: dict[tuple[date, str | None], InvoiceRow] = {}
    rates: dict[tuple[date, str | None], set[float | None]] = {}
    for entry in entries:
        pieces = report.split_periods(entry["start_time"], entry["end_time"], "day")
        cents = report.to_cents(entry["total_pay"])
        shares: list[int | None] = (
            [None] * len(pieces)
            if cents is None
            else list(report.allocate_cents(cents, [secs for _, secs in pieces]))
        )

        for (day, seconds), share in zip(pieces, shares):
            key = (day, entry["project_name"])
            row = groups.get(key)
            if row is None:
                row = InvoiceRow(day, entry["project_name"], 0, None, None)
                groups[key] = row
            row.seconds += seconds
            if share is not None:
                row.cents = (row.cents or 0) + share
            row.description = _join(row.description, entry["description"])
            rates.setdefault(key, set()).add(entry["pay_rate_hourly"])

    for key, row in groups.items():
        # One shared rate can be shown as arithmetic; a mix of them can't
        seen = rates[key]
        row.rate = seen.pop() if len(seen) == 1 else None

    return [groups[key] for key in sorted(groups, key=lambda k: (k[0], k[1] or ""))]


def _join(existing: str | None, addition: str | None) -> str | None:
    if not addition or (existing and addition in existing.split(DESCRIPTION_SEPARATOR)):
        return existing
    return addition if not existing else existing + DESCRIPTION_SEPARATOR + addition


def period_label(document: InvoiceDocument) -> str:
    """e.g. 'Sep 1 - Sep 14', or with years when the period crosses one."""
    same_year = document.period_start.year == document.period_end.year
    pattern = "%b %-d" if same_year else "%b %-d, %Y"
    return (
        f"{document.period_start.strftime(pattern)} - "
        f"{document.period_end.strftime('%b %-d')}"
        + ("" if same_year else f", {document.period_end.year}")
    )


# --- Files ---


def filename(document: InvoiceDocument, extension: str) -> str:
    """
    e.g. techforce-advisors-2026-09-01-2026-09-14-hourly-invoice-patrick-beal-no-12.pdf
    """
    return (
        "-".join(
            [
                _slug(document.client_name),
                document.period_start.isoformat(),
                document.period_end.isoformat(),
                "hourly-invoice",
                _slug(user.full_name(document.user)),
                f"no-{document.number}",
            ]
        )
        + f".{extension}"
    )


def _slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")
