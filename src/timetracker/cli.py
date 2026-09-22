# cli.py
#
# Author: Patrick Beal
#
# Command-line interface (entry point for `tt`)

import functools
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from timetracker import clients, db
from timetracker.errors import TimeTrackerError

app = typer.Typer(no_args_is_help=True)
client_app = typer.Typer(no_args_is_help=True, help="Manage clients.")
project_app = typer.Typer(no_args_is_help=True, help="Manage projects.")
app.add_typer(client_app, name="client")
app.add_typer(project_app, name="project")

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
        raise TimeTrackerError("Use either --pay-rate-hourly or --no-pay-rate, not both.")
    if no_pay_rate:
        return None
    return clients.UNSET if pay_rate is None else pay_rate
