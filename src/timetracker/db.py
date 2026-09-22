# db.py
#
# Author: Patrick Beal
#
# Database handler

import os
import sqlite3 as sq
from pathlib import Path

from pendulum import DateTime

TIMETRACKER_DB = Path(
    os.getenv("TIMETRACKER_DB", "~/TimeTracker/timetracker.db")
).expanduser()


def init_db(db_path: Path = TIMETRACKER_DB):
    """
    Initializes the database, saving to `db_path`.
    Uses migrations to ensure database is fully up to date.

    :params:

    """
    # Make TimeTracker directory if not created
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Connect to database and set schema (doesn't create tables if they already exist)
    conn = sq.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("PRAGMA user_version;")
    current_version = cursor.fetchone()[0]

    # Apply updates
    migrations_dir = Path(__file__).parent / "migrations"
    migrations = sorted(migrations_dir.glob("*.sql"))
    for mig in migrations:
        mig_version = int(mig.stem.split("_")[0])
        if mig_version > current_version:
            with open(mig) as schema_file:
                schema = schema_file.read()
                cursor.executescript(schema)
                cursor.execute(f"PRAGMA user_version = {mig_version};")

    conn.commit()
    conn.close()


def connect(db_path: Path = TIMETRACKER_DB):
    """
    Creates and returns a connection to the database, ensuring it exists.

    :params:
    """
    # Resolve the path
    init_db(db_path)

    # Open connection and set pragmas
    conn = sq.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("PRAGMA foreign_keys = ON;")

    # Set row_factory
    conn.row_factory = sq.Row

    return conn


def resolve_client(conn: sq.Connection, client_name: str | None):
    # If there's no client name passed in, don't need to get an ID
    if not client_name:
        return None

    # Create cursor
    cursor = conn.cursor()

    # Search client_alias table for matching name/alias
    cursor.execute(
        "SELECT client_id FROM client_alias WHERE client_alias_text = ?", (client_name,)
    )
    row = cursor.fetchone()

    # Throw error if client name is not found
    if not row:
        raise ValueError(
            f"Client does not exist: {client_name} not found in database. Create new client first."
        )

    # Return if it is found
    return row["client_id"]


def resolve_project(conn: sq.Connection, project_name: str | None):
    # If there's no project name passed in, don't need to get an ID
    if not project_name:
        return None

    # Create cursor
    cursor = conn.cursor()

    # Search project_alias table for matching name/alias
    cursor.execute(
        "SELECT project_id FROM project_alias WHERE project_alias_text = ?",
        (project_name,),
    )
    row = cursor.fetchone()

    # Throw error if project name is not found
    if not row:
        raise ValueError(
            f"Project does not exist: {project_name} not found in database. Create new project first."
        )

    # Return if it is found
    return row["project_id"]


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
    project_id = resolve_project(conn, project)

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
