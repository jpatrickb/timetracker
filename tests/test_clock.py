import sqlite3 as sq

import pendulum
import pytest
import time_machine
from typer.testing import CliRunner

from timetracker import clients, clock, db
from timetracker.cli import app
from timetracker.errors import TimeTrackerError

# Every test runs at noon local time on this day
NOW = pendulum.local(2026, 9, 22, 12, 0, 0)


@pytest.fixture(autouse=True)
def frozen_time():
    with time_machine.travel(NOW, tick=False):
        yield


@pytest.fixture
def conn(tmp_path):
    with db.connection(tmp_path / "test.db") as conn:
        clients.create_client(conn, "TechForce", pay_rate=35, aliases=["TFA"])
        clients.create_client(conn, "Patea", pay_rate=60)
        clients.create_project(conn, 1, "Website", pay_rate=50)  # project 1, TFA
        clients.create_project(conn, 1, "Pro Forma")  # project 2, TFA at $35
        clients.create_project(conn, 2, "Website")  # project 3, Patea at $60
        yield conn


def at(hhmm: str):
    return clock.parse_time(hhmm)


# --- Parsing and formatting ---


@pytest.mark.parametrize(
    "text, expected",
    [
        ("09:15", pendulum.local(2026, 9, 22, 9, 15)),
        ("9:15:30", pendulum.local(2026, 9, 22, 9, 15, 30)),
        ("2026-09-20 23:05", pendulum.local(2026, 9, 20, 23, 5)),
        ("2026-09-20T23:05:01", pendulum.local(2026, 9, 20, 23, 5, 1)),
    ],
)
def test_parse_time(text, expected):
    assert clock.parse_time(text) == expected


@pytest.fixture
def new_york():
    with pendulum.test_local_timezone(pendulum.timezone("America/New_York")):
        yield


def test_dst_missing_time_moves_forward_and_warns(new_york):
    warnings = []
    parsed = clock.parse_time("2026-03-08 02:30", warn=warnings.append)
    assert parsed == pendulum.datetime(2026, 3, 8, 3, 30, tz="America/New_York")
    assert "doesn't exist" in warnings[0]
    assert "03:30 EDT" in warnings[0]


def test_dst_repeated_time_uses_first_and_warns(new_york):
    warnings = []
    parsed = clock.parse_time("2026-11-01 01:30", warn=warnings.append)
    assert parsed.offset == -4 * 3600  # EDT, the first 1:30
    assert "happens twice" in warnings[0]


def test_normal_time_does_not_warn(new_york):
    warnings = []
    clock.parse_time("2026-11-01 03:30", warn=warnings.append)
    assert warnings == []


def test_future_error_suggests_yesterday(conn):
    entry_id, _ = clock.clock_in(conn, at("2026-09-21 23:00"))
    with time_machine.travel(pendulum.local(2026, 9, 22, 0, 30), tick=False):
        with pytest.raises(TimeTrackerError, match="'2026-09-21 23:50'"):
            clock.clock_out(conn, entry_id, at("23:50"))


@pytest.mark.parametrize("text", ["9", "9am", "25:00", "2026-02-30 09:00", "12:60"])
def test_parse_time_rejects(text):
    with pytest.raises(TimeTrackerError):
        clock.parse_time(text)


def test_format_duration():
    assert clock.format_duration(4 * 3600 + 53 * 60 + 12) == "4:53:12"
    assert clock.format_duration(30 * 3600) == "30:00:00"


# --- Clock in ---


def test_clock_in_defaults_to_now(conn):
    entry_id, overlaps = clock.clock_in(conn)
    entry = clock.get_entry(conn, entry_id)
    assert entry["start_time"] == NOW.int_timestamp
    assert entry["end_time"] is None
    assert overlaps == []


def test_clock_in_future_blocked(conn):
    with pytest.raises(TimeTrackerError, match="future"):
        clock.clock_in(conn, at("12:01"))


def test_project_implies_client_and_rate(conn):
    entry_id, _ = clock.clock_in(conn, project="Pro Forma")
    entry = clock.get_entry(conn, entry_id)
    assert entry["client_name"] == "TechForce"
    assert entry["pay_rate_hourly"] == 35


def test_client_only_uses_client_rate(conn):
    entry_id, _ = clock.clock_in(conn, client="Patea")
    assert clock.get_entry(conn, entry_id)["pay_rate_hourly"] == 60


def test_ambiguous_project_needs_client(conn):
    with pytest.raises(TimeTrackerError, match="more than one client"):
        clock.clock_in(conn, project="Website")
    entry_id, _ = clock.clock_in(conn, client="tfa", project="website")
    assert clock.get_entry(conn, entry_id)["pay_rate_hourly"] == 50


def test_second_clock_in_reports_open_entry(conn):
    first, _ = clock.clock_in(conn, at("09:00"))
    _, overlaps = clock.clock_in(conn)
    assert [e["entry_id"] for e in overlaps] == [first]
    assert len(clock.open_entries(conn)) == 2


# --- Clock out ---


def test_clock_out_computes_pay(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"), client="TFA", project="Website")
    clock.clock_out(conn, entry_id, at("10:30"))
    entry = clock.get_entry(conn, entry_id)
    assert entry["duration"] == 9000
    assert entry["total_pay"] == 125.0


def test_clock_out_appends_description(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"), description="Started X")
    clock.clock_out(conn, entry_id, description="Finished Y")
    assert clock.get_entry(conn, entry_id)["description"] == "Started X\n\nFinished Y"


def test_clock_out_description_when_none_before(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"))
    clock.clock_out(conn, entry_id, description="Finished Y")
    assert clock.get_entry(conn, entry_id)["description"] == "Finished Y"


def test_clock_out_twice_fails(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"))
    clock.clock_out(conn, entry_id)
    with pytest.raises(TimeTrackerError, match="already clocked out"):
        clock.clock_out(conn, entry_id)


def test_clock_out_missing_entry(conn):
    with pytest.raises(TimeTrackerError, match="No entry with ID 99"):
        clock.clock_out(conn, 99)


def test_clock_out_before_start_fails(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"))
    with pytest.raises(TimeTrackerError, match="before start"):
        clock.clock_out(conn, entry_id, at("07:59"))


def test_clock_out_can_span_midnight(conn):
    entry_id, _ = clock.clock_in(conn, at("2026-09-21 22:00"))
    clock.clock_out(conn, entry_id, at("02:00"))
    assert clock.get_entry(conn, entry_id)["duration"] == 4 * 3600


def test_clock_out_ambiguous_project_needs_client(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"), client="TFA", project="Pro Forma")
    # Both clients have a "Website", so --client is required even though
    # the entry already belongs to TFA
    with pytest.raises(TimeTrackerError, match="more than one client"):
        clock.clock_out(conn, entry_id, project="Website")
    clock.clock_out(conn, entry_id, client="TFA", project="Website")
    entry = clock.get_entry(conn, entry_id)
    assert entry["project_id"] == 1
    assert entry["pay_rate_hourly"] == 50


def test_rate_is_taken_at_clock_out(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"), client="TFA", project="Website")
    clients.edit_project(conn, 1, pay_rate=80)
    clock.clock_out(conn, entry_id)
    assert clock.get_entry(conn, entry_id)["pay_rate_hourly"] == 80


def test_closed_entry_keeps_rate_until_refreshed(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"), project="Pro Forma")
    clients.edit_project(conn, 2, pay_rate=80)
    clock.edit_entry(conn, entry_id, description="typo fix")
    assert clock.get_entry(conn, entry_id)["pay_rate_hourly"] == 35
    clock.edit_entry(conn, entry_id, refresh_rate=True)
    assert clock.get_entry(conn, entry_id)["pay_rate_hourly"] == 80


def test_closing_by_edit_takes_current_rate(conn):
    entry_id, _ = clock.clock_in(conn, at("08:00"), project="Pro Forma")
    clients.edit_project(conn, 2, pay_rate=80)
    clock.edit_entry(conn, entry_id, end=at("09:00"))
    assert clock.get_entry(conn, entry_id)["pay_rate_hourly"] == 80


# --- Add, edit, overlaps ---


def test_add_entry_reports_overlap(conn):
    first, _ = clock.add_entry(conn, at("08:00"), at("09:00"))
    _, overlaps = clock.add_entry(conn, at("08:30"), at("09:30"))
    assert [e["entry_id"] for e in overlaps] == [first]


def test_closed_entry_overlaps_open_entry(conn):
    running, _ = clock.clock_in(conn, at("08:00"))
    _, overlaps = clock.add_entry(conn, at("10:00"), at("11:00"))
    assert [e["entry_id"] for e in overlaps] == [running]


def test_back_to_back_is_not_overlap(conn):
    clock.add_entry(conn, at("08:00"), at("09:00"))
    _, overlaps = clock.add_entry(conn, at("09:00"), at("10:00"))
    assert overlaps == []


def test_add_entry_future_end_blocked(conn):
    with pytest.raises(TimeTrackerError, match="future"):
        clock.add_entry(conn, at("11:00"), at("13:00"))


def test_edit_replaces_description_and_times(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"), description="Old")
    clock.edit_entry(conn, entry_id, start=at("07:00"), description="New")
    entry = clock.get_entry(conn, entry_id)
    assert entry["description"] == "New"
    assert entry["duration"] == 2 * 3600


def test_edit_rejects_end_before_start(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"))
    with pytest.raises(TimeTrackerError, match="before start"):
        clock.edit_entry(conn, entry_id, start=at("10:00"))


def test_client_change_clears_mismatched_project(conn):
    entry_id, _ = clock.add_entry(
        conn, at("08:00"), at("09:00"), client="TFA", project="Pro Forma"
    )
    clock.edit_entry(conn, entry_id, client="Patea")
    entry = clock.get_entry(conn, entry_id)
    assert (entry["client_name"], entry["project_id"]) == ("Patea", None)
    assert entry["pay_rate_hourly"] == 60


def test_same_client_keeps_project(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"), project="Pro Forma")
    clock.edit_entry(conn, entry_id, client="tfa")
    assert clock.get_entry(conn, entry_id)["project_name"] == "Pro Forma"


def test_clear_flags(conn):
    entry_id, _ = clock.add_entry(
        conn, at("08:00"), at("09:00"), project="Pro Forma", description="x"
    )
    clock.edit_entry(conn, entry_id, clear_project=True, clear_description=True)
    entry = clock.get_entry(conn, entry_id)
    assert entry["client_name"] == "TechForce"
    assert entry["project_id"] is None
    assert entry["description"] is None
    assert entry["pay_rate_hourly"] == 35  # client rate now

    clock.edit_entry(conn, entry_id, clear_client=True)
    entry = clock.get_entry(conn, entry_id)
    assert entry["client_id"] is None
    assert entry["pay_rate_hourly"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"clear_client": True, "client": "TFA"},
        {"clear_client": True, "project": "Pro Forma"},
        {"clear_project": True, "project": "Pro Forma"},
        {"clear_description": True, "description": "x"},
    ],
)
def test_conflicting_clear_flags(conn, kwargs):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"))
    with pytest.raises(TimeTrackerError, match="can't be combined"):
        clock.edit_entry(conn, entry_id, **kwargs)


def test_reopen(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"))
    clock.edit_entry(conn, entry_id, reopen=True)
    assert [e["entry_id"] for e in clock.open_entries(conn)] == [entry_id]
    with pytest.raises(TimeTrackerError, match="already open"):
        clock.edit_entry(conn, entry_id, reopen=True)


def test_reopen_blocked_on_draft(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"), client="TFA")
    bill(conn, entry_id, status="draft")
    with pytest.raises(TimeTrackerError, match="draft invoice"):
        clock.edit_entry(conn, entry_id, reopen=True)


def test_overlaps_only_reported_when_times_change(conn):
    clock.add_entry(conn, at("08:00"), at("09:00"))
    second, _ = clock.add_entry(conn, at("08:30"), at("09:30"))
    assert clock.edit_entry(conn, second, description="typo") == []
    assert len(clock.edit_entry(conn, second, end=at("09:45"))) == 1


def test_edit_project_to_other_clients_project(conn):
    entry_id, _ = clock.add_entry(
        conn, at("08:00"), at("09:00"), client="Patea", project="Website"
    )
    clock.edit_entry(conn, entry_id, project="Pro Forma")
    entry = clock.get_entry(conn, entry_id)
    assert entry["client_name"] == "TechForce"
    assert entry["pay_rate_hourly"] == 35


def test_db_rejects_project_from_other_client(conn):
    with pytest.raises(sq.IntegrityError):
        conn.execute(
            "INSERT INTO time_entries (start_time, client_id, project_id) VALUES (0, 2, 1)"
        )


# --- Invoice protection ---


def bill(conn, entry_id, status="issued"):
    invoice_id = conn.execute(
        "INSERT INTO invoices (client_id, date_generated, period_start, period_end, status) VALUES (1, 0, '2026-09-01', '2026-09-14', 'draft')"
    ).lastrowid
    conn.execute(
        "INSERT INTO invoice_entries (invoice_id, entry_id) VALUES (?, ?)",
        (invoice_id, entry_id),
    )
    if status == "issued":
        conn.execute(
            "UPDATE invoices SET status = 'issued', invoice_number = 7 "
            "WHERE invoice_id = ?",
            (invoice_id,),
        )


def test_billed_entry_cannot_be_edited_or_deleted(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"), client="TFA")
    bill(conn, entry_id)
    with pytest.raises(TimeTrackerError, match="invoice #7 for TechForce"):
        clock.edit_entry(conn, entry_id, description="x")
    with pytest.raises(TimeTrackerError, match="invoice #7"):
        clock.delete_entry(conn, entry_id)


def test_draft_entry_can_be_deleted(conn):
    entry_id, _ = clock.add_entry(conn, at("08:00"), at("09:00"), client="TFA")
    bill(conn, entry_id, status="draft")
    clock.delete_entry(conn, entry_id)
    assert conn.execute("SELECT COUNT(*) FROM invoice_entries").fetchone()[0] == 0


# --- CLI ---


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "cli.db"))
    runner = CliRunner()
    invoke = lambda *args, input=None: runner.invoke(app, list(args), input=input)  # noqa: E731
    invoke("client", "add", "Acme", "--pay-rate-hourly", "40")
    return invoke


def test_cli_clock_cycle(cli):
    result = cli("in", "--client", "Acme", "--time", "09:00")
    assert result.exit_code == 0
    assert "entry 1" in result.output

    assert "Acme" in cli("status").output

    result = cli("out", "--id", "1")
    assert result.exit_code == 0
    assert "3:00:00" in result.output
    assert "Not clocked in" in cli("status").output


def test_cli_out_without_id_lists_open(cli):
    assert "not clocked in" in cli("out").output
    cli("in")
    cli("in")
    result = cli("out")
    assert result.exit_code == 1
    assert "Open entries: 1, 2" in result.output


def test_cli_delete_asks_first(cli):
    cli("add", "--start-time", "08:00", "--end-time", "09:00")
    assert cli("delete", "1", input="n\n").exit_code == 1
    assert cli("delete", "1", input="y\n").exit_code == 0
    assert "No entry with ID 1" in cli("edit", "1", "--desc", "x").output


def test_cli_client_change_offers_projects(cli, monkeypatch):
    from timetracker import cli as cli_module

    monkeypatch.setattr(cli_module, "_interactive", lambda: True)
    cli("client", "add", "Other", "--pay-rate-hourly", "90")
    cli("project", "add", "Acme", "Site")
    cli("project", "add", "Other", "Portal")
    cli("add", "--start-time", "08:00", "--end-time", "09:00", "--project", "Site")

    result = cli("edit", "1", "--client", "Other", input="1\n")
    assert "Site belongs to Acme, so it will be cleared" in result.output
    assert "1. Portal" in result.output
    # delete's confirmation table shows the entry; answer no to keep it
    assert "Portal" in cli("delete", "1", input="n\n").output


def test_cli_client_change_non_interactive_clears(cli):
    cli("client", "add", "Other")
    cli("project", "add", "Acme", "Site")
    cli("add", "--start-time", "08:00", "--end-time", "09:00", "--project", "Site")
    result = cli("edit", "1", "--client", "Other")
    assert result.exit_code == 0
    assert "will be cleared" in result.output


def test_cli_watch_clocks_out_on_enter(cli):
    result = cli("in", "--time", "11:00", "--watch", input="\nwrapped up\n")
    assert result.exit_code == 0
    assert "Clocked out: entry 1" in result.output
    assert "Not clocked in" in cli("status").output
