from types import SimpleNamespace
from typing import cast

import pendulum
import pytest
import typer

from timetracker import clients, clock, completion, db, invoice


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A database with two clients, three projects, and a few entries."""
    path = tmp_path / "data" / "test.db"
    monkeypatch.setenv("TIMETRACKER_DB", str(path))

    with db.connection(path) as conn:
        clients.create_client(conn, "TechForce Advisors", pay_rate=35, aliases=["TFA"])
        clients.create_client(conn, "Patea", pay_rate=60)
        clients.create_project(conn, 1, "Extraction")
        clients.create_project(conn, 1, "Pro Forma")
        clients.create_project(conn, 2, "Wedding Platform")

        clock.add_entry(
            conn,
            pendulum.now().subtract(days=1, hours=2),
            pendulum.now().subtract(days=1),
            client="TFA",
            project="Extraction",
        )
        clock.clock_in(conn, pendulum.now().subtract(hours=1), client="Patea")
        yield conn


def context(**params) -> typer.Context:
    """A stand-in for the click context, which only params are read from."""
    return cast(typer.Context, SimpleNamespace(params=params))


# --- Clients and projects ---


def test_clients_include_aliases_with_the_full_name_as_help(data):
    assert completion.clients("") == [
        ("Patea", ""),
        ("TechForce Advisors", ""),
        ("TFA", "TechForce Advisors"),
    ]


def test_completion_filters_case_insensitively(data):
    assert completion.clients("tf") == [("TFA", "TechForce Advisors")]
    assert completion.clients("pat") == [("Patea", "")]
    assert completion.clients("zzz") == []


def test_projects_narrow_to_the_chosen_client(data):
    everything = [name for name, _ in completion.projects(context(), "")]
    assert everything == ["Extraction", "Pro Forma", "Wedding Platform"]

    scoped = [name for name, _ in completion.projects(context(client="TFA"), "")]
    assert scoped == ["Extraction", "Pro Forma"]


def test_projects_show_their_client_as_help(data):
    assert completion.projects(context(), "wed") == [
        ("Wedding Platform", "Patea"),
    ]


# --- Entries ---


def test_open_entries_are_only_the_running_ones(data):
    assert [entry_id for entry_id, _ in completion.open_entries("")] == ["2"]


def test_entries_are_newest_first_with_a_label(data):
    listed = completion.entries("")
    assert [entry_id for entry_id, _ in listed] == ["2", "1"]
    assert listed[1][1].startswith("TechForce Advisors/Extraction, ")


# --- Invoices ---


def test_invoice_completions_match_the_command(data):
    first = invoice.create_draft(
        data, 1, pendulum.now().date(), pendulum.now().date(), [1]
    )
    assert [i for i, _ in completion.draft_invoices("")] == [str(first)]
    assert completion.issued_invoices("") == []

    invoice.issue(data, first)
    assert completion.draft_invoices("") == []
    assert [i for i, _ in completion.issued_invoices("")] == [str(first)]
    assert [i for i, _ in completion.any_invoices("")] == [str(first)]


def test_invoice_help_shows_client_period_and_number(data):
    invoice_id = invoice.create_draft(
        data, 1, pendulum.now().date(), pendulum.now().date(), [1]
    )
    ((_, help_text),) = completion.draft_invoices("")
    assert help_text.startswith("TechForce Advisors, ")
    assert help_text.endswith("(draft)")

    invoice.issue(data, invoice_id)
    ((_, help_text),) = completion.issued_invoices("")
    assert help_text.endswith("#1")


# --- Fields ---


def test_fields_complete_one_name_at_a_time(data):
    assert completion.report_fields("pro") == ["project"]
    assert completion.report_fields("id,pro") == ["id,project"]
    # Already-chosen names aren't offered again
    assert "id,id" not in completion.report_fields("id,i")
    assert completion.report_fields("id,")[0].startswith("id,")


# --- Safety ---


def test_completion_is_silent_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "missing.db"))
    assert completion.clients("") == []
    assert completion.entries("") == []
    assert completion.draft_invoices("") == []
    assert completion.projects(context(), "") == []


def test_completion_never_creates_a_database(tmp_path, monkeypatch):
    """Pressing Tab shouldn't write anything, or even make the folder."""
    path = tmp_path / "nested" / "missing.db"
    monkeypatch.setenv("TIMETRACKER_DB", str(path))
    completion.clients("")
    assert not path.exists()
    assert not path.parent.exists()


def test_completion_survives_a_damaged_database(tmp_path, monkeypatch):
    path = tmp_path / "broken.db"
    path.write_text("this is not a database")
    monkeypatch.setenv("TIMETRACKER_DB", str(path))
    assert completion.clients("") == []
    assert completion.open_entries("") == []
