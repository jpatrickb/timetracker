# cli.py
#
# Author: Patrick Beal
#
# Command-line interface (entry point for `tt`)

import functools
import sqlite3 as sq
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from pathlib import Path

from timetracker import clients, clock, db, invoice, report, tui, user
from timetracker.formats import default_filename
from timetracker.formats.delimited import render_csv, render_tsv
from timetracker.formats.json_format import render_json
from timetracker.formats.table import render_markdown, render_table
from timetracker.errors import TimeTrackerError

app = typer.Typer(no_args_is_help=True)
client_app = typer.Typer(no_args_is_help=True, help="Manage clients.")
project_app = typer.Typer(no_args_is_help=True, help="Manage projects.")
app.add_typer(client_app, name="client")
invoice_app = typer.Typer(no_args_is_help=True, help="Manage invoices.")
user_app = typer.Typer(no_args_is_help=True, help="Your details, used on invoices.")
app.add_typer(project_app, name="project")
app.add_typer(invoice_app, name="invoice")
app.add_typer(user_app, name="user")

console = Console()
err_console = Console(stderr=True)


def handle_errors(func):
    """Prints TimeTrackerErrors as a one-line message and exits with status 1."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except TimeTrackerError as e:
            err_console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    return wrapper


def format_rate(rate: float | None) -> str:
    return "—" if rate is None else f"${rate:,.2f}/hr"


# Reused option types
PayRate = Annotated[
    float | None, typer.Option("--pay-rate-hourly", help="Hourly billing rate.")
]
Aliases = Annotated[
    list[str] | None,
    typer.Option("--alias", help="Alternate name. Repeat for several."),
]
Client = Annotated[str | None, typer.Option("--client", help="Client name or alias.")]
Project = Annotated[
    str | None,
    typer.Option("--project", help="Project name or alias. Implies its client."),
]
TIME_FORMAT = "HH:MM[:SS], optionally after YYYY-MM-DD"
TIME_HELP = f"{TIME_FORMAT}. Defaults to now."


# --- Clients ---


@client_app.command("add")
@handle_errors
def client_add(
    name: Annotated[str, typer.Argument(help="Client name.")],
    pay_rate: PayRate = None,
    alias: Annotated[
        list[str] | None,
        typer.Option(
            "--alias", "--client-alias", help="Alternate name. Repeat for several."
        ),
    ] = None,
):
    """Create a new client."""
    with db.connection() as conn:
        client_id = clients.create_client(conn, name, pay_rate, alias)
    console.print(f"Created client [bold]{name}[/bold] (ID {client_id})")


@client_app.command("edit")
@handle_errors
def client_edit(
    name: Annotated[
        str | None, typer.Argument(help="Client name or alias.", show_default=False)
    ] = None,
    client_id: Annotated[
        int | None, typer.Option("--id", help="Client ID, instead of a name.")
    ] = None,
    new_name: Annotated[
        str | None, typer.Option("--new-client", help="Rename the client.")
    ] = None,
    pay_rate: PayRate = None,
    alias: Aliases = None,
):
    """
    Rename a client, change its rate, or add aliases.

    A new rate also updates every project still on the client's old rate.
    """
    with db.connection() as conn:
        client_id = _client_id(conn, name, client_id)
        clients.edit_client(conn, client_id, new_name, pay_rate, alias)
    console.print("Client updated.")


@client_app.command("list")
@handle_errors
def client_list():
    """List all clients."""
    with db.connection() as conn:
        rows = clients.list_clients(conn)

    table = Table("ID", "Client", "Rate", "Aliases")
    for row in rows:
        table.add_row(
            str(row["client_id"]),
            row["client_name"],
            format_rate(row["pay_rate_hourly"]),
            row["aliases"] or "",
        )
    console.print(table)


def _client_id(conn, name: str | None, client_id: int | None) -> int:
    """Resolves a client given either a name/alias or an --id."""
    if (name is None) == (client_id is None):
        raise TimeTrackerError("Give a client name or --id (one, not both).")

    if client_id is not None:
        if not conn.execute(
            "SELECT 1 FROM clients WHERE client_id = ?", (client_id,)
        ).fetchone():
            raise TimeTrackerError(f"No client with ID {client_id}.")
        return client_id

    resolved = clients.resolve_client(conn, name)
    assert resolved is not None
    return resolved


# --- Projects ---


@project_app.command("add")
@handle_errors
def project_add(
    client: Annotated[str, typer.Argument(help="Client name or alias.")],
    name: Annotated[str, typer.Argument(help="Project name.")],
    pay_rate: PayRate = None,
    no_pay_rate: Annotated[
        bool, typer.Option("--no-pay-rate", help="Give the project no rate at all.")
    ] = False,
    alias: Aliases = None,
):
    """
    Create a new project for a client.

    Without --pay-rate-hourly the project uses the client's rate, and follows
    it when the client's rate changes.
    """
    rate = _rate_option(pay_rate, no_pay_rate)
    with db.connection() as conn:
        client_id = clients.resolve_client(conn, client)
        assert client_id is not None
        project_id = clients.create_project(conn, client_id, name, rate, alias)
    console.print(f"Created project [bold]{name}[/bold] (ID {project_id})")


@project_app.command("edit")
@handle_errors
def project_edit(
    client: Annotated[str, typer.Argument(help="Client name or alias.")],
    project: Annotated[str, typer.Argument(help="Project name or alias.")],
    new_name: Annotated[
        str | None, typer.Option("--new-project", help="Rename the project.")
    ] = None,
    pay_rate: PayRate = None,
    no_pay_rate: Annotated[
        bool, typer.Option("--no-pay-rate", help="Remove the project's rate.")
    ] = False,
    alias: Aliases = None,
):
    """Rename a project, change its rate, or add aliases."""
    rate = _rate_option(pay_rate, no_pay_rate)
    with db.connection() as conn:
        client_id = clients.resolve_client(conn, client)
        project_id = clients.resolve_project(conn, project, client_id)
        assert project_id is not None
        clients.edit_project(conn, project_id, new_name, rate, alias)
    console.print("Project updated.")


@project_app.command("list")
@handle_errors
def project_list(
    client: Annotated[
        str | None,
        typer.Argument(help="Only show this client's projects.", show_default=False),
    ] = None,
):
    """List projects, optionally for one client."""
    with db.connection() as conn:
        client_id = clients.resolve_client(conn, client)
        rows = clients.list_projects(conn, client_id)

    table = Table("ID", "Client", "Project", "Rate", "Aliases")
    for row in rows:
        table.add_row(
            str(row["project_id"]),
            row["client_name"],
            row["project_name"],
            format_rate(row["pay_rate_hourly"]),
            row["aliases"] or "",
        )
    console.print(table)


def _rate_option(pay_rate: float | None, no_pay_rate: bool):
    """Turns the two rate flags into a rate, None, or UNSET (flag not given)."""
    if no_pay_rate and pay_rate is not None:
        raise TimeTrackerError(
            "Use either --pay-rate-hourly or --no-pay-rate, not both."
        )
    if no_pay_rate:
        return None
    return clients.UNSET if pay_rate is None else pay_rate


# --- Time entries ---


def _warn(message: str):
    err_console.print(f"[yellow]Warning:[/yellow] {message}")


def _parse(text: str | None):
    """Parses an optional time flag, warning if DST made it ambiguous."""
    return clock.parse_time(text, warn=_warn) if text else None


def _interactive() -> bool:
    return sys.stdin.isatty()


def _project_after_client_change(
    conn: sq.Connection, entry_id: int, client: str | None, project: str | None
) -> str | None:
    """
    When --client moves an entry to a different client and no --project was
    given, the entry's old project no longer fits and gets cleared. In an
    interactive terminal, offer the new client's projects to pick from.
    Returns the --project value to use.
    """
    if not client or project:
        return project

    entry = clock.get_entry(conn, entry_id)
    client_id = clients.resolve_client(conn, client)
    if entry["project_id"] is None or entry["client_id"] == client_id:
        return None

    console.print(
        f"Project [bold]{entry['project_name']}[/bold] belongs to "
        f"{entry['client_name']}, so it will be cleared."
    )
    projects = clients.list_projects(conn, client_id)
    if not projects or not _interactive():
        return None

    for number, row in enumerate(projects, start=1):
        console.print(f"  {number}. {row['project_name']}")
    while True:
        choice = typer.prompt(
            "Pick a project by number or name (Enter for none)",
            default="",
            show_default=False,
        ).strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(projects):
            return projects[int(choice) - 1]["project_name"]
        try:
            clients.resolve_project(conn, choice, client_id)
            return choice
        except TimeTrackerError as e:
            err_console.print(f"[red]{e}[/red]")


def _label(entry: sq.Row) -> str:
    """e.g. 'TechForce Advisors / Website', or 'no client'."""
    parts = [p for p in (entry["client_name"], entry["project_name"]) if p]
    return " / ".join(parts) or "no client"


def _warn_overlaps(overlaps: list[sq.Row]):
    for entry in overlaps:
        if entry["end_time"] is None:
            span = f"clocked in since {clock.format_timestamp(entry['start_time'])}"
        else:
            span = (
                f"{clock.format_timestamp(entry['start_time'])} to "
                f"{clock.format_timestamp(entry['end_time'])}"
            )
        _warn(f"overlaps entry {entry['entry_id']} ({_label(entry)}, {span})")


@app.command("in")
@handle_errors
def clock_in(
    time: Annotated[str | None, typer.Option("--time", help=TIME_HELP)] = None,
    client: Client = None,
    project: Project = None,
    desc: Annotated[
        str | None, typer.Option("--desc", help="What you're working on.")
    ] = None,
    watch: Annotated[
        bool, typer.Option("--watch", help="Show a running timer until you clock out.")
    ] = False,
):
    """Clock in. Prints the entry ID you'll need to clock out."""
    with db.connection() as conn:
        entry_id, overlaps = clock.clock_in(conn, _parse(time), client, project, desc)
        entry = clock.get_entry(conn, entry_id)
        _warn_overlaps(overlaps)
        console.print(
            f"Clocked in: entry [bold]{entry_id}[/bold] ({_label(entry)}) "
            f"at {clock.format_timestamp(entry['start_time'])}"
        )
        if watch:
            _watch(conn, entry)


def _watch(conn: sq.Connection, entry: sq.Row):
    """Opens the full-screen watch view over an open entry."""
    outcome = tui.run_watch(conn, entry["entry_id"])
    if outcome == "clocked out":
        _print_clocked_out(clock.get_entry(conn, entry["entry_id"]))
    elif outcome == "closed elsewhere":
        console.print(f"Entry {entry['entry_id']} was clocked out elsewhere.")
    else:
        console.print(f"Detached. Still clocked in as entry {entry['entry_id']}.")


def _print_clocked_out(entry: sq.Row):
    console.print(
        f"Clocked out: entry [bold]{entry['entry_id']}[/bold] ({_label(entry)}), "
        f"{clock.format_duration(entry['duration'])}"
    )


@app.command("out")
@handle_errors
def clock_out(
    entry_id: Annotated[
        int | None, typer.Option("--id", help="Entry to clock out of.")
    ] = None,
    time: Annotated[str | None, typer.Option("--time", help=TIME_HELP)] = None,
    client: Client = None,
    project: Project = None,
    desc: Annotated[
        str | None,
        typer.Option("--desc", help="Added to the end of the existing description."),
    ] = None,
):
    """Clock out of an entry. A new client or project replaces the old one."""
    with db.connection() as conn:
        if entry_id is None:
            open_ids = [str(e["entry_id"]) for e in clock.open_entries(conn)]
            if not open_ids:
                raise TimeTrackerError("You're not clocked in.")
            raise TimeTrackerError(
                f"Pass --id to choose an entry. Open entries: {', '.join(open_ids)}"
            )

        project = _project_after_client_change(conn, entry_id, client, project)
        overlaps = clock.clock_out(conn, entry_id, _parse(time), client, project, desc)
        _warn_overlaps(overlaps)
        _print_clocked_out(clock.get_entry(conn, entry_id))


@app.command("watch")
@handle_errors
def watch(
    entry_id: Annotated[
        int | None, typer.Option("--id", help="Which open entry to attach to.")
    ] = None,
):
    """Attach the live view to an entry you're already clocked in to."""
    with db.connection() as conn:
        if entry_id is None:
            open_entries = clock.open_entries(conn)
            if not open_entries:
                raise TimeTrackerError("You're not clocked in.")
            if len(open_entries) > 1:
                ids = ", ".join(str(e["entry_id"]) for e in open_entries)
                raise TimeTrackerError(f"Pass --id to choose. Open entries: {ids}")
            entry_id = int(open_entries[0]["entry_id"])

        entry = clock.get_entry(conn, entry_id)
        if entry["end_time"] is not None:
            raise TimeTrackerError(f"Entry {entry_id} is already clocked out.")
        _watch(conn, entry)


@app.command("add")
@handle_errors
def add(
    start_time: Annotated[str, typer.Option("--start-time", help=TIME_FORMAT)],
    end_time: Annotated[str, typer.Option("--end-time", help=TIME_FORMAT)],
    client: Client = None,
    project: Project = None,
    desc: Annotated[
        str | None, typer.Option("--desc", help="What you worked on.")
    ] = None,
):
    """Log a finished entry with both start and end times."""
    with db.connection() as conn:
        entry_id, overlaps = clock.add_entry(
            conn,
            clock.parse_time(start_time, warn=_warn),
            clock.parse_time(end_time, warn=_warn),
            client,
            project,
            desc,
        )
        entry = clock.get_entry(conn, entry_id)
    _warn_overlaps(overlaps)
    console.print(
        f"Added entry [bold]{entry_id}[/bold] ({_label(entry)}), "
        f"{clock.format_duration(entry['duration'])}"
    )


@app.command("edit")
@handle_errors
def edit(
    entry_id: Annotated[int, typer.Argument(help="Entry to edit.")],
    start_time: Annotated[
        str | None, typer.Option("--start-time", help=TIME_FORMAT)
    ] = None,
    end_time: Annotated[
        str | None, typer.Option("--end-time", help=TIME_FORMAT)
    ] = None,
    client: Client = None,
    project: Project = None,
    desc: Annotated[
        str | None, typer.Option("--desc", help="Replaces the existing description.")
    ] = None,
    no_client: Annotated[
        bool, typer.Option("--no-client", help="Remove the client (and project).")
    ] = False,
    no_project: Annotated[
        bool, typer.Option("--no-project", help="Remove the project.")
    ] = False,
    no_desc: Annotated[
        bool, typer.Option("--no-desc", help="Remove the description.")
    ] = False,
    reopen: Annotated[
        bool, typer.Option("--reopen", help="Clear the end time, clocking back in.")
    ] = False,
    refresh_rate: Annotated[
        bool,
        typer.Option(
            "--refresh-rate", help="Use the project's (or client's) current rate."
        ),
    ] = False,
):
    """Correct an entry's times, client, project, description, or rate."""
    with db.connection() as conn:
        project = _project_after_client_change(conn, entry_id, client, project)
        overlaps = clock.edit_entry(
            conn,
            entry_id,
            _parse(start_time),
            _parse(end_time),
            client,
            project,
            desc,
            clear_client=no_client,
            clear_project=no_project,
            clear_description=no_desc,
            reopen=reopen,
            refresh_rate=refresh_rate,
        )
    _warn_overlaps(overlaps)
    console.print(f"Entry {entry_id} updated.")


@app.command("delete")
@handle_errors
def delete(
    entry_id: Annotated[int, typer.Argument(help="Entry to delete.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation.")
    ] = False,
):
    """Delete an entry permanently."""
    with db.connection() as conn:
        entry = clock.get_entry(conn, entry_id)
        if not yes:
            _print_entries([entry])
            typer.confirm(f"Delete entry {entry_id}?", abort=True)
        clock.delete_entry(conn, entry_id)
    console.print(f"Deleted entry {entry_id}.")


@app.command("status")
@handle_errors
def status():
    """Show whether you're clocked in, and to what."""
    with db.connection() as conn:
        entries = clock.open_entries(conn)
    if not entries:
        console.print("Not clocked in.")
        return
    _print_entries(entries)


def _print_entries(entries: list[sq.Row]):
    table = Table("ID", "Client", "Project", "Start", "End", "Duration", "Description")
    for e in entries:
        is_open = e["end_time"] is None
        duration = clock.now() - e["start_time"] if is_open else e["duration"]
        table.add_row(
            str(e["entry_id"]),
            e["client_name"] or "",
            e["project_name"] or "",
            clock.format_timestamp(e["start_time"]),
            "open" if is_open else clock.format_timestamp(e["end_time"]),
            clock.format_duration(duration),
            e["description"] or "",
        )
    console.print(table)


# --- Reports ---

# Output format -> (renderer, file extension). The terminal table is printed
# directly, so it has no renderer to a string and can't be written to disk.
TEXT_OUTPUTS = {
    "md": (render_markdown, "md"),
    "json": (render_json, "json"),
    "csv": (render_csv, "csv"),
    "tsv": (render_tsv, "tsv"),
}

# Binary formats can't be piped, so these always write a file
FILE_OUTPUTS = ("pdf", "xlsx")
OUTPUTS = ("table", *TEXT_OUTPUTS, *FILE_OUTPUTS)


@app.command("report")
@handle_errors
def report_command(
    client: Annotated[
        list[str] | None,
        typer.Option("--client", help="Only this client. Repeat for several."),
    ] = None,
    project: Annotated[
        list[str] | None,
        typer.Option("--project", help="Only this project. Repeat for several."),
    ] = None,
    start: Annotated[
        str | None, typer.Option("--start", help="First day, YYYY-MM-DD.")
    ] = None,
    end: Annotated[
        str | None, typer.Option("--end", help="Last day (inclusive), YYYY-MM-DD.")
    ] = None,
    group_by: Annotated[
        str, typer.Option("--group-by", help="entry, day, week, or month.")
    ] = "entry",
    fields: Annotated[
        str | None,
        typer.Option("--fields", help="Comma-separated columns, e.g. id,project,pay."),
    ] = None,
    output: Annotated[
        str,
        typer.Option("--output", help="table, md, json, csv, tsv, pdf, or xlsx."),
    ] = "table",
    write: Annotated[
        bool, typer.Option("--write", help="Save to the reports folder.")
    ] = False,
    filename: Annotated[
        str | None,
        typer.Option(
            "--filename", help="File name or path to save to. Implies --write."
        ),
    ] = None,
    make_invoice: Annotated[
        bool,
        typer.Option("--invoice", help="Create a draft invoice from this selection."),
    ] = False,
    include_billed: Annotated[
        bool,
        typer.Option(
            "--include-billed",
            help="With --invoice, also include entries already billed.",
        ),
    ] = False,
):
    """
    Report logged time. Defaults to this week, one row per entry.

    Entries count toward the range they start in. Open entries are left out.
    """
    if make_invoice:
        _make_invoice(client, project, start, end, output, include_billed)
        return
    if include_billed:
        raise TimeTrackerError(
            "--include-billed only applies with --invoice. Reports include "
            "billed entries already."
        )
    if group_by not in report.GROUP_BY_OPTIONS:
        raise TimeTrackerError(
            f"Unknown --group-by '{group_by}'. Use {', '.join(report.GROUP_BY_OPTIONS)}."
        )
    if output not in OUTPUTS:
        raise TimeTrackerError(
            f"Unknown --output '{output}'. Use {', '.join(OUTPUTS)}."
        )
    if (write or filename) and output == "table":
        raise TimeTrackerError(
            "The terminal table can't be saved. Use --output md instead."
        )

    with db.connection() as conn:
        result = report.build_report(
            conn,
            clients=client,
            projects=project,
            start=report.parse_date(start) if start else None,
            end=report.parse_date(end) if end else None,
            group_by=group_by,  # type: ignore[arg-type]  # checked above
            fields=[f.strip() for f in fields.split(",")] if fields else None,
        )

    if result.skipped_open:
        plural = "entry" if result.skipped_open == 1 else "entries"
        _warn(f"{result.skipped_open} open {plural} not included.")

    if output == "table":
        console.print(render_table(result))
        return

    if output in FILE_OUTPUTS:
        path = _report_path(filename or default_filename(result, output))
        if output == "pdf":
            from timetracker.formats.pdf import render_report_pdf

            render_report_pdf(result, path)
        else:
            from timetracker.formats.xlsx import render_report_xlsx

            render_report_xlsx(result, path)
        console.print(f"Saved {path}")
        return

    render, extension = TEXT_OUTPUTS[output]
    text = render(result)
    if not (write or filename):
        # Plain print, not Rich, so the output can be piped or redirected as-is
        sys.stdout.write(text)
        return

    path = _report_path(filename or default_filename(result, extension))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    console.print(f"Saved {path}")


def _make_invoice(
    client: list[str] | None,
    project: list[str] | None,
    start: str | None,
    end: str | None,
    output: str,
    include_billed: bool,
):
    """
    Creates a draft invoice from a report selection and writes its file.

    Entries already on an issued invoice are left out unless --include-billed
    is passed, which is what prevents double billing.
    """
    if output == "table":
        output = "pdf"
    _check_invoice_output(output)

    with db.connection() as conn:
        # Checked before anything is created, so a missing address can't
        # leave a draft behind
        user.require_user(conn)

        result = report.build_report(
            conn,
            clients=client,
            projects=project,
            start=report.parse_date(start) if start else None,
            end=report.parse_date(end) if end else None,
            include_billed=include_billed,
        )
        if result.skipped_open:
            plural = "entry" if result.skipped_open == 1 else "entries"
            _warn(f"{result.skipped_open} open {plural} not invoiced.")

        if len(result.client_ids) > 1:
            names = ", ".join(sorted({str(row["client"]) for row in result.rows}))
            raise TimeTrackerError(
                f"An invoice covers one client, but this selection has {names}. "
                "Narrow it with --client."
            )
        if not result.entry_ids or result.client_ids == [None]:
            raise TimeTrackerError(
                "No billable entries for that selection. Entries need a client, "
                "and billed ones are excluded unless you pass --include-billed."
            )

        invoice_id = invoice.create_draft(
            conn,
            result.client_ids[0],
            result.start or result.first_day or result.end,
            result.end,
            result.entry_ids,
        )
        try:
            path = _render_invoice(conn, invoice_id, output)
        except Exception:
            # Don't leave a draft behind if the file couldn't be written
            invoice.delete_draft(conn, invoice_id)
            raise

    console.print(
        f"Created draft invoice [bold]{invoice_id}[/bold] with "
        f"{len(result.entry_ids)} entries. Saved {path}"
    )
    console.print(f"Issue it with `tt invoice issue {invoice_id}` when you send it.")


def _report_path(filename: str) -> Path:
    """
    A bare file name goes in the reports folder next to the database. A name
    with a folder in it is used as given, relative to the current directory.
    """
    path = Path(filename).expanduser()
    if path.is_absolute() or len(path.parts) > 1:
        return path
    return db.resolve_db_path().parent / "reports" / path


# --- Invoices ---

INVOICE_OUTPUTS = ("pdf", "xlsx")


def _render_invoice(conn: sq.Connection, invoice_id: int, output: str) -> Path:
    """Builds the document and writes it to the invoices folder."""
    document = invoice.build_document(conn, invoice_id)
    path = db.resolve_db_path().parent / "invoices" / invoice.filename(document, output)

    if output == "pdf":
        from timetracker.formats.pdf import render_pdf

        render_pdf(document, path)
    else:
        from timetracker.formats.xlsx import render_xlsx

        render_xlsx(document, path)
    return path


@invoice_app.command("list")
@handle_errors
def invoice_list():
    """List invoices. Draft numbers are the one they'd get if issued."""
    with db.connection() as conn:
        rows = invoice.list_invoices(conn)

    table = Table("ID", "Number", "Client", "Period", "Status", "Hours", "Total")
    for row in rows:
        number = f"#{row['invoice_number']}"
        if row["predicted"]:
            number += " (predicted)"
        table.add_row(
            str(row["invoice_id"]),
            number,
            row["client_name"],
            f"{row['period_start']} to {row['period_end']}",
            row["status"],
            clock.format_duration(row["seconds"]),
            "" if row["cents"] is None else f"${row['cents'] / 100:,.2f}",
        )
    console.print(table)


@invoice_app.command("issue")
@handle_errors
def invoice_issue(
    invoice_id: Annotated[int, typer.Argument(help="Draft to issue.")],
    output: Annotated[str, typer.Option("--output", help="pdf or xlsx.")] = "pdf",
):
    """
    Issue a draft: allocate its number, mark its entries billed, and write
    the file again with the confirmed number.
    """
    _check_invoice_output(output)
    with db.connection() as conn:
        number = invoice.issue(conn, invoice_id)
        path = _render_invoice(conn, invoice_id, output)
    console.print(f"Issued invoice #{number}. Saved {path}")


@invoice_app.command("void")
@handle_errors
def invoice_void(
    invoice_id: Annotated[int, typer.Argument(help="Issued invoice to void.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation.")
    ] = False,
):
    """Void an issued invoice, releasing its entries to be billed again."""
    with db.connection() as conn:
        if not yes:
            typer.confirm(f"Void invoice {invoice_id}?", abort=True)
        invoice.void(conn, invoice_id)
    console.print(f"Invoice {invoice_id} voided. Its number stays reserved.")


@invoice_app.command("delete")
@handle_errors
def invoice_delete(
    invoice_id: Annotated[int, typer.Argument(help="Draft to delete.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation.")
    ] = False,
):
    """Delete a draft invoice. Issued and void invoices are kept."""
    with db.connection() as conn:
        if not yes:
            typer.confirm(f"Delete draft invoice {invoice_id}?", abort=True)
        invoice.delete_draft(conn, invoice_id)
    console.print(f"Deleted draft invoice {invoice_id}.")


@invoice_app.command("regenerate")
@handle_errors
def invoice_regenerate(
    invoice_id: Annotated[int, typer.Argument(help="Invoice to write again.")],
    output: Annotated[str, typer.Option("--output", help="pdf or xlsx.")] = "pdf",
):
    """
    Write an invoice's file again from its linked entries, so it matches the
    one that was issued rather than re-running the original filters.
    """
    _check_invoice_output(output)
    with db.connection() as conn:
        path = _render_invoice(conn, invoice_id, output)
    console.print(f"Saved {path}")


def _check_invoice_output(output: str):
    if output not in INVOICE_OUTPUTS:
        raise TimeTrackerError(
            f"Invoices are {' or '.join(INVOICE_OUTPUTS)}, not '{output}'."
        )


# --- Setup and user details ---


@app.command("setup")
@handle_errors
def setup():
    """Choose where the database lives and enter your invoice details."""
    configured = db.CONFIG_PATH.expanduser()
    current = db.resolve_db_path()
    chosen = typer.prompt("Database location", default=str(current))
    if Path(chosen).expanduser() != current:
        configured.parent.mkdir(parents=True, exist_ok=True)
        configured.write_text(f'db_path = "{chosen}"\n')
        console.print(f"Saved database location to {configured}")

    with db.connection(chosen) as conn:
        existing = user.get_user(conn)
        values = {}
        for field in user.WIZARD_ORDER:
            default = (existing[field] if existing else None) or ""
            optional = " (optional)" if field in user.OPTIONAL_FIELDS else ""
            values[field] = typer.prompt(
                f"{user.LABELS[field]}{optional}",
                default=default,
                show_default=bool(default),
            )
        user.save_user(conn, **values)
    console.print("Setup complete.")


@user_app.command("show")
@handle_errors
def user_show():
    """Show the details that appear on your invoices."""
    with db.connection() as conn:
        details = user.get_user(conn)
    if details is None:
        console.print("No details yet. Run `tt setup`.")
        return

    table = Table("Field", "Value", show_header=False)
    for field in user.FIELDS:
        table.add_row(user.LABELS[field], details[field] or "")
    console.print(table)


@user_app.command("edit")
@handle_errors
def user_edit(
    first_name: Annotated[str | None, typer.Option("--first-name")] = None,
    last_name: Annotated[str | None, typer.Option("--last-name")] = None,
    address_line_1: Annotated[str | None, typer.Option("--address")] = None,
    address_line_2: Annotated[str | None, typer.Option("--address-2")] = None,
    city: Annotated[str | None, typer.Option("--city")] = None,
    state: Annotated[str | None, typer.Option("--state")] = None,
    zip_code: Annotated[str | None, typer.Option("--zip")] = None,
    email: Annotated[str | None, typer.Option("--email")] = None,
    phone: Annotated[str | None, typer.Option("--phone")] = None,
    payment_notes: Annotated[
        str | None,
        typer.Option("--payment-notes", help="Shown at the bottom of an invoice."),
    ] = None,
):
    """Change one or more of your details."""
    values = {
        "first_name": first_name,
        "last_name": last_name,
        "address_line_1": address_line_1,
        "address_line_2": address_line_2,
        "city": city,
        "state": state,
        "zip_code": zip_code,
        "email": email,
        "phone": phone,
        "payment_notes": payment_notes,
    }
    if not any(v is not None for v in values.values()):
        raise TimeTrackerError("Nothing to change. Pass at least one option.")

    with db.connection() as conn:
        user.save_user(conn, **values)
    console.print("Details updated.")
