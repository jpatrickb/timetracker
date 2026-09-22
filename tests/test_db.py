import sqlite3 as sq

import pytest

from timetracker import db


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture
def no_config(tmp_path, monkeypatch):
    """Point the config file somewhere empty and clear the env var."""
    monkeypatch.setattr(db, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.delenv("TIMETRACKER_DB", raising=False)
    return tmp_path / "config.toml"


# --- Path resolution ---


def test_explicit_path_wins(no_config, monkeypatch, tmp_path):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "env.db"))
    no_config.write_text(f'db_path = "{tmp_path / "config.db"}"')
    assert db.resolve_db_path(tmp_path / "explicit.db") == tmp_path / "explicit.db"


def test_env_beats_config(no_config, monkeypatch, tmp_path):
    monkeypatch.setenv("TIMETRACKER_DB", str(tmp_path / "env.db"))
    no_config.write_text(f'db_path = "{tmp_path / "config.db"}"')
    assert db.resolve_db_path() == tmp_path / "env.db"


def test_config_beats_default(no_config, tmp_path):
    no_config.write_text(f'db_path = "{tmp_path / "config.db"}"')
    assert db.resolve_db_path() == tmp_path / "config.db"


@pytest.mark.usefixtures("no_config")
def test_default_path():
    assert db.resolve_db_path() == db.DEFAULT_DB_PATH.expanduser()


def test_connect_creates_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "test.db"
    db.connect(path).close()
    assert path.exists()


# --- Migrations ---


def test_fresh_db_is_at_latest_version(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "test.db"
    db.connect(path).close()
    conn = db.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    conn.close()


def test_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_failed_migration_rolls_back(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_good.sql").write_text("CREATE TABLE a (x INTEGER);")
    (migrations / "002_bad.sql").write_text(
        "CREATE TABLE b (x INTEGER);\nTHIS IS NOT SQL;"
    )

    conn = sq.connect(tmp_path / "test.db")
    with pytest.raises(sq.Error):
        db.migrate(conn, migrations)

    # 001 applied, 002 left no trace
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "a" in tables
    assert "b" not in tables
    conn.close()


def test_newer_db_is_refused(tmp_path):
    conn = sq.connect(tmp_path / "test.db")
    conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="version 99"):
        db.migrate(conn)
    conn.close()


# --- Invoice constraints ---


def make_client(conn, name):
    return conn.execute(
        "INSERT INTO clients (client_name) VALUES (?)", (name,)
    ).lastrowid


def make_entry(conn, client_id):
    return conn.execute(
        "INSERT INTO time_entries (start_time, end_time, client_id) VALUES (0, 3600, ?)",
        (client_id,),
    ).lastrowid


def make_invoice(conn, client_id, entry_ids):
    invoice_id = conn.execute(
        "INSERT INTO invoices (client_id, date_generated, period_start, period_end, status) VALUES (?, 0, '2026-09-01', '2026-09-14', 'draft')",
        (client_id,),
    ).lastrowid
    for entry_id in entry_ids:
        conn.execute(
            "INSERT INTO invoice_entries (invoice_id, entry_id) VALUES (?, ?)",
            (invoice_id, entry_id),
        )
    return invoice_id


def issue(conn, invoice_id, number):
    conn.execute(
        "UPDATE invoices SET status = 'issued', invoice_number = ? WHERE invoice_id = ?",
        (number, invoice_id),
    )


def test_entry_can_sit_on_many_drafts(conn):
    client = make_client(conn, "Acme")
    entry = make_entry(conn, client)
    make_invoice(conn, client, [entry])
    make_invoice(conn, client, [entry])


def test_issue_blocks_double_billing(conn):
    client = make_client(conn, "Acme")
    entry = make_entry(conn, client)
    first = make_invoice(conn, client, [entry])
    second = make_invoice(conn, client, [entry])
    issue(conn, first, 1)
    with pytest.raises(sq.IntegrityError, match="already billed"):
        issue(conn, second, 2)


def test_voiding_releases_entries(conn):
    client = make_client(conn, "Acme")
    entry = make_entry(conn, client)
    first = make_invoice(conn, client, [entry])
    second = make_invoice(conn, client, [entry])
    issue(conn, first, 1)
    conn.execute("UPDATE invoices SET status = 'void' WHERE invoice_id = ?", (first,))
    issue(conn, second, 2)


def test_cannot_link_entry_to_issued_invoice(conn):
    client = make_client(conn, "Acme")
    invoice = make_invoice(conn, client, [])
    issue(conn, invoice, 1)
    entry = make_entry(conn, client)
    with pytest.raises(sq.IntegrityError, match="draft"):
        conn.execute(
            "INSERT INTO invoice_entries (invoice_id, entry_id) VALUES (?, ?)",
            (invoice, entry),
        )


@pytest.mark.parametrize("entry_client", ["other", None])
def test_entry_client_must_match_invoice(conn, entry_client):
    client = make_client(conn, "Acme")
    other = make_client(conn, "Other")
    entry = make_entry(conn, other if entry_client == "other" else None)
    with pytest.raises(sq.IntegrityError, match="different client"):
        make_invoice(conn, client, [entry])


def test_draft_cannot_have_number(conn):
    client = make_client(conn, "Acme")
    with pytest.raises(sq.IntegrityError):
        conn.execute(
            "INSERT INTO invoices (client_id, invoice_number, date_generated, period_start, period_end, status) "
            "VALUES (?, 1, 0, '2026-09-01', '2026-09-14', 'draft')",
            (client,),
        )


def test_issued_requires_number(conn):
    client = make_client(conn, "Acme")
    invoice = make_invoice(conn, client, [])
    with pytest.raises(sq.IntegrityError):
        conn.execute(
            "UPDATE invoices SET status = 'issued' WHERE invoice_id = ?", (invoice,)
        )


def test_invoice_numbers_are_per_client(conn):
    acme = make_client(conn, "Acme")
    other = make_client(conn, "Other")
    issue(conn, make_invoice(conn, acme, []), 1)
    issue(conn, make_invoice(conn, other, []), 1)
    with pytest.raises(sq.IntegrityError):
        issue(conn, make_invoice(conn, acme, []), 1)


def test_open_entry_cannot_be_invoiced(conn):
    client = make_client(conn, "Acme")
    entry = conn.execute(
        "INSERT INTO time_entries (start_time, client_id) VALUES (0, ?)", (client,)
    ).lastrowid
    with pytest.raises(sq.IntegrityError, match="open entries"):
        make_invoice(conn, client, [entry])


def test_invoiced_entry_cannot_be_reopened(conn):
    client = make_client(conn, "Acme")
    entry = make_entry(conn, client)
    make_invoice(conn, client, [entry])
    with pytest.raises(sq.IntegrityError, match="cannot be reopened"):
        conn.execute(
            "UPDATE time_entries SET end_time = NULL WHERE entry_id = ?", (entry,)
        )


# --- User info ---


def test_only_one_user_row(conn):
    row = ("Pat", "Beal", "1 Main St", None, "Boston", "MA", "02134")
    conn.execute(
        "INSERT INTO user_info (first_name, last_name, address_line_1, address_line_2, "
        "city, state, zip_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    assert conn.execute("SELECT zip_code FROM user_info").fetchone()[0] == "02134"
    with pytest.raises(sq.IntegrityError):
        conn.execute(
            "INSERT INTO user_info (first_name, last_name, address_line_1, "
            "address_line_2, city, state, zip_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
            row,
        )


@pytest.mark.parametrize(
    "start, end",
    [
        ("2026-09-14", "2026-09-01"),
        ("2026-02-30", "2026-03-01"),
        ("9/1/2026", "2026-09-14"),
    ],
)
def test_invoice_period_must_be_valid(conn, start, end):
    client = make_client(conn, "Acme")
    with pytest.raises(sq.IntegrityError):
        conn.execute(
            "INSERT INTO invoices (client_id, date_generated, period_start, period_end, "
            "status) VALUES (?, 0, ?, ?, 'draft')",
            (client, start, end),
        )
