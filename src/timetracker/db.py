# db.py
#
# Author: Patrick Beal
#
# Database handler

import os
import sqlite3 as sq
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pendulum import DateTime

from timetracker.clients import resolve_client, resolve_project

DEFAULT_DB_PATH = Path("~/TimeTracker/timetracker.db")
CONFIG_PATH = Path("~/.config/timetracker/config.toml")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """
    Works out which database file to use.

    Preference order: explicit argument, then the `TIMETRACKER_DB` environment
    variable, then `db_path` in the config file, then the default location.
    """
    if db_path is None:
        db_path = os.getenv("TIMETRACKER_DB")

    # Only read the config file if nothing more specific was given
    if not db_path:
        config_file = CONFIG_PATH.expanduser()
        if config_file.exists():
            with open(config_file, "rb") as f:
                db_path = tomllib.load(f).get("db_path")

    return Path(db_path or DEFAULT_DB_PATH).expanduser()


def migrate(conn: sq.Connection, migrations_dir: Path = MIGRATIONS_DIR):
    """
    Brings the database schema up to date by applying any migrations newer than
    the version stored in `PRAGMA user_version`.

    Each migration runs in its own transaction along with its version bump, so a
    failing migration leaves the database exactly as it was before that step.
    """
    current_version = conn.execute("PRAGMA user_version;").fetchone()[0]

    migrations = sorted(migrations_dir.glob("*.sql"))
    latest_version = int(migrations[-1].stem.split("_")[0]) if migrations else 0

    # A newer app version already migrated this file--refuse rather than guess
    if current_version > latest_version:
        raise RuntimeError(
            f"Database is at schema version {current_version}, but this version of "
            f"timetracker only knows up to {latest_version}. Upgrade timetracker."
        )

    for mig in migrations:
        mig_version = int(mig.stem.split("_")[0])
        if mig_version <= current_version:
            continue

        # executescript commits any open transaction before it runs, so the
        # BEGIN/COMMIT have to live inside the script itself
        script = f"BEGIN;\n{mig.read_text()}\nPRAGMA user_version = {mig_version};\nCOMMIT;"
        try:
            conn.executescript(script)
        except sq.Error:
            if conn.in_transaction:
                conn.rollback()
            raise


def connect(db_path: str | Path | None = None) -> sq.Connection:
    """
    Opens a connection to the database, creating the directory and applying
    migrations first if needed.
    """
    path = resolve_db_path(db_path)

    # Make TimeTracker directory if not created
    path.parent.mkdir(parents=True, exist_ok=True)

    # The foreign_keys pragma is ignored inside a transaction, so it has to run
    # before anything opens one
    conn = sq.connect(path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sq.Row

    migrate(conn)

    return conn


@contextmanager
def connection(db_path: str | Path | None = None) -> Iterator[sq.Connection]:
    """
    `with db.connection() as conn:` opens the database and always closes it.
    (sqlite3's own `with conn:` only commits or rolls back, it never closes.)
    """
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_pay_rate(conn: sq.Connection, client_id: int | None, project_id: int | None):
    cursor = conn.cursor()

    # Default pay rate is Null
    pay_rate = None

    # Check clients and projects table for pay rates--projects table supercedes, if it exists
    if project_id:
        cursor.execute(
            "SELECT pay_rate_hourly FROM projects WHERE project_id = ?", (project_id,)
        )
        pay_rate = cursor.fetchone()["pay_rate_hourly"]

    elif client_id:
        cursor.execute(
            "SELECT pay_rate_hourly FROM clients WHERE client_id = ?", (client_id,)
        )
        pay_rate = cursor.fetchone()["pay_rate_hourly"]

    return pay_rate


def start_entry(
    conn: sq.Connection,
    start_time: DateTime,
    end_time: DateTime | None = None,
    client: str | None = None,
    project: str | None = None,
    description: str | None = None,
):
    cursor = conn.cursor()

    # Get client and project id
    client_id = resolve_client(conn, client)
    project_id = resolve_project(conn, project, client_id)

    # Get pay rate
    pay_rate = get_pay_rate(conn, client_id, project_id)

    # Insert into database
    cursor.execute(
        """INSERT INTO time_entries 
            (start_time, end_time, client_id, project_id, description, pay_rate_hourly)
        VALUES (:start_time, :end_time, :client_id, :project_id, :description, :pay_rate_hourly)""",
        {
            "start_time": start_time.int_timestamp,
            "end_time": end_time.int_timestamp if end_time else None,
            "client_id": client_id,
            "project_id": project_id,
            "description": description,
            "pay_rate_hourly": pay_rate,
        },
    )

    # Get entry id
    entry_id = cursor.lastrowid

    return entry_id


def end_entry(
    conn: sq.Connection,
    entry_id: int,  # needed so that we can close the right time entry
    end_time: DateTime,
    start_time: DateTime | None = None,
    client: str | None = None,
    project: str | None = None,
    description: str | None = None,
):
    cursor = conn.cursor()

    # Get start_time, client, project, and description so we can check for changes and handle overwrites intentionally
    cursor.execute("""
        SELECT (start_time, client, project, description)
        FROM time_entries
        WHERE (entry_id = :entry_id)
    """)

    # Check for overwrites and handle (appending description, overwriting client and project)


def get_open_entries(conn: sq.Connection):
    cursor = conn.cursor()

    cursor.execute(
        """SELECT (entry_id, start_time, client_id, project_id, description) 
        from time_entries 
        WHERE end_time IS NULL 
        ORDER BY start_time ASC;"""
    )

    rows = cursor.fetchall()

    return rows
