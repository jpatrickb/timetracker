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
        script = (
            f"BEGIN;\n{mig.read_text()}\nPRAGMA user_version = {mig_version};\nCOMMIT;"
        )
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
