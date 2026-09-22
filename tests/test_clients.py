import pytest
from typer.testing import CliRunner

from timetracker import clients, db
from timetracker.cli import app
from timetracker.errors import TimeTrackerError


@pytest.fixture
def conn(tmp_path):
    with db.connection(tmp_path / "test.db") as conn:
        yield conn


def rate_of(conn, project_id):
    return conn.execute(
        "SELECT pay_rate_hourly FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()[0]


# --- Clients and aliases ---


def test_client_resolves_by_name_and_alias_any_case(conn):
    client = clients.create_client(conn, "TechForce Advisors", aliases=["TFA"])
    assert clients.resolve_client(conn, "techforce advisors") == client
    assert clients.resolve_client(conn, "tfa") == client


def test_unknown_client_raises(conn):
    with pytest.raises(TimeTrackerError, match="not found"):
        clients.resolve_client(conn, "Nobody")


def test_alias_cannot_collide_with_other_client_name(conn):
    clients.create_client(conn, "G8")
    with pytest.raises(TimeTrackerError, match="already used by client G8"):
        clients.create_client(conn, "G8 Capital", aliases=["g8"])


def test_failed_create_leaves_nothing_behind(conn):
    clients.create_client(conn, "G8")
    with pytest.raises(TimeTrackerError):
        clients.create_client(conn, "G8 Capital", aliases=["G8"])
    names = [r["client_name"] for r in clients.list_clients(conn)]
    assert names == ["G8"]


def test_rename_keeps_old_name_as_alias(conn):
    client = clients.create_client(conn, "Old Name")
    clients.edit_client(conn, client, new_name="New Name")
    assert clients.resolve_client(conn, "Old Name") == client
    assert clients.resolve_client(conn, "New Name") == client


def test_rename_to_own_alias(conn):
    client = clients.create_client(conn, "G8 Capital", aliases=["G8"])
    clients.edit_client(conn, client, new_name="G8")
    assert clients.list_clients(conn)[0]["client_name"] == "G8"


def test_rename_to_other_clients_alias_fails(conn):
    clients.create_client(conn, "G8 Capital", aliases=["G8"])
    other = clients.create_client(conn, "Other")
    with pytest.raises(TimeTrackerError, match="alias of G8 Capital"):
        clients.edit_client(conn, other, new_name="G8")


def test_negative_rate_rejected(conn):
    with pytest.raises(TimeTrackerError, match="negative"):
        clients.create_client(conn, "Acme", pay_rate=-1)


# --- Projects and rates ---


def test_project_inherits_client_rate(conn):
    client = clients.create_client(conn, "Acme", pay_rate=35)
    project = clients.create_project(conn, client, "Site")
    assert rate_of(conn, project) == 35


def test_project_explicit_no_rate(conn):
    client = clients.create_client(conn, "Acme", pay_rate=35)
    project = clients.create_project(conn, client, "Pro bono", pay_rate=None)
    assert rate_of(conn, project) is None


def test_client_rate_cascades_only_to_matching_projects(conn):
    client = clients.create_client(conn, "Acme", pay_rate=35)
    inherited = clients.create_project(conn, client, "Inherited")
    custom = clients.create_project(conn, client, "Custom", pay_rate=50)
    clients.edit_client(conn, client, pay_rate=40)
    assert rate_of(conn, inherited) == 40
    assert rate_of(conn, custom) == 50


def test_cascade_from_no_rate(conn):
    client = clients.create_client(conn, "Acme")
    project = clients.create_project(conn, client, "Site")
    clients.edit_client(conn, client, pay_rate=40)
    assert rate_of(conn, project) == 40


def test_cascade_is_per_client(conn):
    acme = clients.create_client(conn, "Acme", pay_rate=35)
    other = clients.create_client(conn, "Other", pay_rate=35)
    other_project = clients.create_project(conn, other, "Site")
    clients.edit_client(conn, acme, pay_rate=40)
    assert rate_of(conn, other_project) == 35


def test_edit_project_rate(conn):
    client = clients.create_client(conn, "Acme", pay_rate=35)
    project = clients.create_project(conn, client, "Site")
    clients.edit_project(conn, project, new_name="Website")
    assert rate_of(conn, project) == 35  # UNSET leaves it alone
    clients.edit_project(conn, project, pay_rate=None)
    assert rate_of(conn, project) is None


# --- Project name scoping ---


def test_same_project_name_for_two_clients(conn):
    acme = clients.create_client(conn, "Acme")
    other = clients.create_client(conn, "Other")
    acme_site = clients.create_project(conn, acme, "Website")
    other_site = clients.create_project(conn, other, "website")
    assert clients.resolve_project(conn, "WEBSITE", acme) == acme_site
    assert clients.resolve_project(conn, "WEBSITE", other) == other_site


def test_ambiguous_project_without_client(conn):
    clients.create_project(conn, clients.create_client(conn, "Acme"), "Website")
    clients.create_project(conn, clients.create_client(conn, "Other"), "Website")
    with pytest.raises(TimeTrackerError, match="more than one client"):
        clients.resolve_project(conn, "Website")


def test_unique_project_resolves_without_client(conn):
    client = clients.create_client(conn, "Acme")
    project = clients.create_project(conn, client, "Website", aliases=["web"])
    assert clients.resolve_project(conn, "WEB") == project


def test_project_alias_unique_within_client(conn):
    client = clients.create_client(conn, "Acme")
    clients.create_project(conn, client, "Website")
    with pytest.raises(TimeTrackerError, match="already used"):
        clients.create_project(conn, client, "Web App", aliases=["website"])


def test_project_from_wrong_client_not_found(conn):
    acme = clients.create_client(conn, "Acme")
    other = clients.create_client(conn, "Other")
    clients.create_project(conn, acme, "Website")
    with pytest.raises(TimeTrackerError, match="not found"):
        clients.resolve_project(conn, "Website", other)


# --- CLI ---


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "cli.db"))
    runner = CliRunner()
    return lambda *args: runner.invoke(app, list(args))


def test_cli_add_and_list(cli):
    assert (
        cli(
            "client", "add", "Acme", "--client-alias", "AC", "--pay-rate-hourly", "35"
        ).exit_code
        == 0
    )
    assert cli("project", "add", "ac", "Website").exit_code == 0
    result = cli("project", "list", "Acme")
    assert "Website" in result.output
    assert "$35.00/hr" in result.output


def test_cli_error_is_clean(cli):
    result = cli("project", "add", "Nobody", "Website")
    assert result.exit_code == 1
    assert "Client not found" in result.output
    assert "Traceback" not in result.output


def test_cli_rate_flags_conflict(cli):
    cli("client", "add", "Acme")
    result = cli(
        "project", "add", "Acme", "Site", "--pay-rate-hourly", "5", "--no-pay-rate"
    )
    assert result.exit_code == 1
