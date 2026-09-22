# tui.py
#
# Author: Patrick Beal
#
# The `--watch` full-screen view: a live clock, the running session, and an
# editable description, over an entry that stays open until you clock out

import sqlite3 as sq

import pendulum
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Digits, Footer, Input, Label, Static, TextArea

from timetracker import clock
from timetracker.errors import TimeTrackerError

# How often the description is written back while you type
AUTOSAVE_SECONDS = 15


class Details(Vertical):
    """Client, project, and start time, each editable in place."""

    BORDER_TITLE = "Details"

    def compose(self) -> ComposeResult:
        yield Label("Client")
        yield Input(id="client", placeholder="none")
        yield Label("Project")
        yield Input(id="project", placeholder="none")
        yield Label("Started")
        yield Input(id="start", placeholder="HH:MM")
        yield Label("", id="rate")


class WallClock(Vertical):
    """The current time, in big seven-segment digits."""

    BORDER_TITLE = "Time"

    def compose(self) -> ComposeResult:
        yield Digits(_now_text(), id="wall")


class Session(Vertical):
    """Elapsed time, and what it's worth so far."""

    BORDER_TITLE = "Session"

    def compose(self) -> ComposeResult:
        yield Label("Elapsed")
        yield Digits("0:00:00", id="elapsed")
        yield Label("", id="earned")


class WatchApp(App):
    """
    Five panels: details, a wall clock, the session totals, the description,
    and the day's entries.
    """

    TITLE = "Time Tracker"

    CSS = """
    Screen { layout: grid; grid-size: 3 2; grid-columns: 1fr 2fr 1fr; grid-rows: 9 1fr; }
    Details, #wall-clock, Session, #description, #today {
        border: round $primary; padding: 0 1;
    }
    Details:focus-within, #description:focus-within { border: round $accent; }
    #description { column-span: 2; }
    #wall-clock, Session { align: center middle; }
    #wall-clock Digits, Session Digits { width: auto; }
    Session Label { width: auto; }
    Details Label { color: $text-muted; }
    Details Input { border: none; padding: 0; height: 1; background: $surface; }
    #rate, #earned { color: $success; }
    TextArea { border: none; }
    """

    # priority so they still fire while the description has focus
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+d", "detach", "Detach", priority=True),
        Binding("ctrl+o", "clock_out", "Clock out", priority=True),
    ]

    def __init__(self, conn: sq.Connection, entry_id: int):
        super().__init__()
        self.conn = conn
        self.entry_id = entry_id
        self.entry = clock.get_entry(conn, entry_id)
        self.saved_description = self.entry["description"] or ""
        self.seconds_since_save = 0
        # Set on exit so the CLI can say what happened
        self.outcome = "detached"

    def compose(self) -> ComposeResult:
        yield Details()
        yield WallClock(id="wall-clock")
        yield Session()
        yield TextArea(self.saved_description, id="description")
        yield Static(id="today")
        yield Footer()

    def on_mount(self):
        self.sub_title = _label(self.entry)
        self.query_one("#description").border_title = "Description"
        self.query_one("#today").border_title = "Today"
        self.load_details()
        self.refresh_panels()
        self.set_interval(1, self.tick)

    # --- Live updates ---

    def tick(self):
        """Once a second: redraw the clocks and autosave the description."""
        self.entry = clock.get_entry(self.conn, self.entry_id)
        if self.entry["end_time"] is not None:
            # Something else clocked this entry out while we were attached
            self.outcome = "closed elsewhere"
            self.exit()
            return

        self.query_one("#wall", Digits).update(_now_text())
        self.refresh_panels()

        self.seconds_since_save += 1
        if self.seconds_since_save >= AUTOSAVE_SECONDS:
            self.save_description()

    def refresh_panels(self):
        elapsed = clock.now() - self.entry["start_time"]
        self.query_one("#elapsed", Digits).update(clock.format_duration(elapsed))

        rate = clock.get_pay_rate(
            self.conn, self.entry["client_id"], self.entry["project_id"]
        )
        earned = "" if rate is None else f"Earned  ${rate * elapsed / 3600:,.2f}"
        self.query_one("#earned", Label).update(earned)
        self.query_one("#rate", Label).update(
            "No rate" if rate is None else f"${rate:,.2f}/hr"
        )
        self.query_one("#today", Static).update(self.today_table())

    def today_table(self) -> Table:
        """The day's entries, with the attached one marked."""
        # expand so the name column actually gets the leftover width
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(justify="right")
        # Names get cut off rather than wrapped, so rows stay one line each
        table.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
        table.add_column(justify="right", no_wrap=True)
        table.add_column(no_wrap=True)

        total = 0
        for entry in _todays_entries(self.conn):
            running = entry["end_time"] is None
            seconds = (
                clock.now() - entry["start_time"] if running else entry["duration"]
            )
            total += seconds
            table.add_row(
                str(entry["entry_id"]),
                _short_label(entry),
                clock.format_duration(seconds),
                "[green]●[/green]" if entry["entry_id"] == self.entry_id else "",
            )
        table.add_row("", Text("Total", style="bold"), clock.format_duration(total), "")
        return table

    # --- Details editing ---

    def load_details(self):
        """Fills the detail inputs from the database."""
        self.query_one("#client", Input).value = self.entry["client_name"] or ""
        self.query_one("#project", Input).value = self.entry["project_name"] or ""
        self.query_one("#start", Input).value = pendulum.from_timestamp(
            self.entry["start_time"], tz="local"
        ).format("YYYY-MM-DD HH:mm:ss")

    def on_input_submitted(self):
        """Enter in any detail field applies all three."""
        client = self.query_one("#client", Input).value.strip()
        project = self.query_one("#project", Input).value.strip()
        start = self.query_one("#start", Input).value.strip()

        # Only changed fields are sent. Leaving the client alone while
        # changing the project lets the project imply its own client, the
        # same as `tt edit --project`.
        client_changed = client != (self.entry["client_name"] or "")
        project_changed = project != (self.entry["project_name"] or "")

        clear_client = client_changed and not client and not project
        clear_project = project_changed and not project and not clear_client

        try:
            clock.edit_entry(
                self.conn,
                self.entry_id,
                start=clock.parse_time(start, warn=self.notify_warning)
                if start
                else None,
                client=client if client_changed and client else None,
                project=project if project_changed and project else None,
                clear_client=clear_client,
                clear_project=clear_project,
            )
        except TimeTrackerError as e:
            self.notify(str(e), severity="error", timeout=8)
        else:
            self.notify("Details updated.")

        self.entry = clock.get_entry(self.conn, self.entry_id)
        self.sub_title = _label(self.entry)
        self.load_details()
        self.refresh_panels()

    def notify_warning(self, message: str):
        self.notify(message, severity="warning", timeout=8)

    # --- Description ---

    def save_description(self) -> bool:
        """Writes the description back if it changed. True if it saved."""
        self.seconds_since_save = 0
        text = self.query_one("#description", TextArea).text
        if text == self.saved_description:
            return False

        # description=None means "unchanged", so clearing needs its own flag
        clock.edit_entry(
            self.conn,
            self.entry_id,
            description=text or None,
            clear_description=not text,
        )
        self.saved_description = text
        return True

    # --- Actions ---

    def action_save(self):
        self.notify("Description saved." if self.save_description() else "No changes.")

    def action_detach(self):
        self.save_description()
        self.outcome = "detached"
        self.exit()

    def action_clock_out(self):
        self.save_description()
        clock.clock_out(self.conn, self.entry_id)
        self.outcome = "clocked out"
        self.exit()


def _now_text() -> str:
    return pendulum.now().format("HH:mm:ss")


def _label(entry: sq.Row) -> str:
    """Full label, e.g. 'TechForce Advisors/Website'."""
    parts = [p for p in (entry["client_name"], entry["project_name"]) if p]
    return "/".join(parts) or "no client"


def _short_label(entry: sq.Row) -> str:
    """Just enough to tell rows apart in the narrow Today panel."""
    return entry["project_name"] or entry["client_name"] or "no client"


def _todays_entries(conn: sq.Connection) -> list[sq.Row]:
    """Entries that started today (local), plus anything still open."""
    midnight = pendulum.today().int_timestamp
    return conn.execute(
        """
        SELECT e.entry_id, e.start_time, e.end_time, e.duration,
            c.client_name, p.project_name
        FROM time_entries AS e
        LEFT JOIN clients AS c ON c.client_id = e.client_id
        LEFT JOIN projects AS p ON p.project_id = e.project_id
        WHERE e.start_time >= ? OR e.end_time IS NULL
        ORDER BY e.start_time
        """,
        (midnight,),
    ).fetchall()


def run_watch(conn: sq.Connection, entry_id: int) -> str:
    """Opens the watch view. Returns what happened, for the CLI to report."""
    app = WatchApp(conn, entry_id)
    app.run()
    return app.outcome
