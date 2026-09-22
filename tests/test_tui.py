import asyncio

import pendulum
import pytest
from rich.console import Console
from textual.widgets import Digits, Input, Label, TextArea

from timetracker import clients, clock, db
from timetracker.tui import WatchApp

# The TUI runs on an asyncio loop, so these tests don't freeze the clock the
# way the others do. Entries are placed relative to now instead.


@pytest.fixture
def conn(tmp_path):
    with db.connection(tmp_path / "test.db") as conn:
        clients.create_client(conn, "TechForce", pay_rate=35, aliases=["TFA"])
        clients.create_client(conn, "Patea", pay_rate=60)
        clients.create_project(conn, 1, "Website", pay_rate=50)
        clients.create_project(conn, 2, "Portal")
        yield conn


@pytest.fixture
def entry_id(conn):
    """An entry clocked in two hours ago, on TechForce/Website at $50."""
    started = pendulum.now().subtract(hours=2)
    entry_id, _ = clock.clock_in(
        conn, started, client="TFA", project="Website", description="First note"
    )
    return entry_id


def drive(conn, entry_id, script):
    """Runs the app, hands it to `script`, and returns the finished app."""

    async def run():
        app = WatchApp(conn, entry_id)
        async with app.run_test() as pilot:
            await script(app, pilot)
        return app

    return asyncio.run(run())


def text_of(app, selector, widget_type=Label):
    return str(app.query_one(selector, widget_type).render())


# --- Panels ---


def test_panels_show_the_session(conn, entry_id):
    async def script(app, pilot):
        assert app.query_one("#client", Input).value == "TechForce"
        assert app.query_one("#project", Input).value == "Website"
        assert "$50.00/hr" in text_of(app, "#rate")

        elapsed = str(app.query_one("#elapsed", Digits).value)
        assert elapsed.startswith("2:00:0")
        # Two hours at $50 is about $100, give or take the second it took
        assert text_of(app, "#earned").startswith("Earned  $100.0")

        assert app.query_one("#description", TextArea).text == "First note"

    drive(conn, entry_id, script)


def test_today_panel_lists_entries_and_total(conn, entry_id):
    clock.add_entry(
        conn,
        pendulum.now().subtract(hours=4),
        pendulum.now().subtract(hours=3),
        client="Patea",
        project="Portal",
    )

    async def script(app, pilot):
        console = Console(width=60)
        with console.capture() as captured:
            console.print(app.today_table())
        rendered = captured.get()

        assert "Portal" in rendered  # the other entry, shown by project
        assert "Website" in rendered
        assert "Total" in rendered
        assert "●" in rendered  # marks the entry being watched

    drive(conn, entry_id, script)


def test_entry_without_rate_shows_no_money(conn):
    plain_id, _ = clock.clock_in(conn, pendulum.now().subtract(minutes=5))

    async def script(app, pilot):
        assert text_of(app, "#rate") == "No rate"
        assert text_of(app, "#earned") == ""

    drive(conn, plain_id, script)


# --- Description ---


def test_ctrl_s_saves_the_description(conn, entry_id):
    async def script(app, pilot):
        area = app.query_one("#description", TextArea)
        area.text = "Rewritten note"
        await pilot.press("ctrl+s")

    drive(conn, entry_id, script)
    assert clock.get_entry(conn, entry_id)["description"] == "Rewritten note"


def test_emptying_the_description_clears_it(conn, entry_id):
    async def script(app, pilot):
        app.query_one("#description", TextArea).text = ""
        await pilot.press("ctrl+s")

    drive(conn, entry_id, script)
    assert clock.get_entry(conn, entry_id)["description"] is None


# --- Details editing ---


def test_editing_project_updates_entry_and_rate(conn, entry_id):
    async def script(app, pilot):
        project = app.query_one("#project", Input)
        project.value = "Portal"  # belongs to Patea
        project.focus()
        await pilot.press("enter")
        assert "$60.00/hr" in text_of(app, "#rate")

    drive(conn, entry_id, script)
    entry = clock.get_entry(conn, entry_id)
    assert (entry["client_name"], entry["project_name"]) == ("Patea", "Portal")


def test_blanking_the_client_clears_both(conn, entry_id):
    async def script(app, pilot):
        app.query_one("#client", Input).value = ""
        app.query_one("#project", Input).value = ""
        app.query_one("#client", Input).focus()
        await pilot.press("enter")

    drive(conn, entry_id, script)
    entry = clock.get_entry(conn, entry_id)
    assert (entry["client_id"], entry["project_id"]) == (None, None)


def test_bad_client_is_rejected_and_fields_reset(conn, entry_id):
    async def script(app, pilot):
        client = app.query_one("#client", Input)
        client.value = "Nobody"
        client.focus()
        await pilot.press("enter")
        # The panel goes back to what's actually stored
        assert client.value == "TechForce"

    drive(conn, entry_id, script)
    assert clock.get_entry(conn, entry_id)["client_name"] == "TechForce"


# --- Leaving ---


def test_detach_saves_but_keeps_the_entry_open(conn, entry_id):
    async def script(app, pilot):
        app.query_one("#description", TextArea).text = "Saved on detach"
        await pilot.press("ctrl+d")

    app = drive(conn, entry_id, script)
    assert app.outcome == "detached"
    entry = clock.get_entry(conn, entry_id)
    assert entry["end_time"] is None
    assert entry["description"] == "Saved on detach"


def test_clock_out_closes_the_entry(conn, entry_id):
    async def script(app, pilot):
        await pilot.press("ctrl+o")

    app = drive(conn, entry_id, script)
    assert app.outcome == "clocked out"
    entry = clock.get_entry(conn, entry_id)
    assert entry["end_time"] is not None
    # The rate is taken at clock-out, so the pay is filled in
    assert entry["total_pay"] == pytest.approx(100, abs=0.5)


def test_clocking_out_elsewhere_ends_the_view(conn, entry_id):
    async def script(app, pilot):
        clock.clock_out(conn, entry_id)
        app.tick()

    app = drive(conn, entry_id, script)
    assert app.outcome == "closed elsewhere"
