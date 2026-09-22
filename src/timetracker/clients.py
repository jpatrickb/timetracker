# clients.py
#
# Author: Patrick Beal
#
# Client and project management: creation, edits, aliases, and name lookup

import sqlite3 as sq
from typing import Final

from timetracker.errors import TimeTrackerError


class _Unset:
    def __repr__(self):
        return "UNSET"


# Default for a project's pay rate, meaning "not given". Distinct from None,
# which means "explicitly no pay rate"
UNSET: Final = _Unset()


# --- Lookup ---


def resolve_client(conn: sq.Connection, client_name: str | None) -> int | None:
    """
    Finds a client ID by name or alias (case-insensitive). Returns None if no
    name was given, and raises if the name doesn't match any client.
    """
    if not client_name:
        return None

    row = conn.execute(
        "SELECT client_id FROM client_alias WHERE client_alias_text = ?",
        (client_name,),
    ).fetchone()

    if not row:
        raise TimeTrackerError(
            f"Client not found: '{client_name}'. Create it first with `tt client add`."
        )

    return row[0]


def resolve_project(
    conn: sq.Connection, project_name: str | None, client_id: int | None = None
) -> int | None:
    """
    Finds a project ID by name or alias (case-insensitive). Project names are
    only unique per client, so without a client_id the name must match exactly
    one project across all clients.
    """
    if not project_name:
        return None

    query = "SELECT project_id, client_id FROM project_alias WHERE project_alias_text = ?"
    params: tuple = (project_name,)
    if client_id is not None:
        query += " AND client_id = ?"
        params += (client_id,)

    rows = conn.execute(query, params).fetchall()

    if not rows:
        raise TimeTrackerError(
            f"Project not found: '{project_name}'. Create it first with `tt project add`."
        )

    if len(rows) > 1:
        clients = ", ".join(_client_name(conn, row[1]) for row in rows)
        raise TimeTrackerError(
            f"Project '{project_name}' exists for more than one client ({clients}). "
            "Pass --client to choose."
        )

    return rows[0][0]


def _client_name(conn: sq.Connection, client_id: int) -> str:
    return conn.execute(
        "SELECT client_name FROM clients WHERE client_id = ?", (client_id,)
    ).fetchone()[0]


def _check_rate(pay_rate: float | None):
    if pay_rate is not None and pay_rate < 0:
        raise TimeTrackerError(f"Pay rate can't be negative: {pay_rate}")


# --- Clients ---


def create_client(
    conn: sq.Connection,
    name: str,
    pay_rate: float | None = None,
    aliases: list[str] | None = None,
) -> int:
    """
    Creates a client and registers its name as its first alias, so lookups only
    ever need to search the alias table.
    """
    _check_rate(pay_rate)

    # `with conn` commits if the block finishes and rolls back if it raises, so
    # a client is never left half-created without its aliases
    with conn:
        try:
            client_id = conn.execute(
                "INSERT INTO clients (client_name, pay_rate_hourly) VALUES (?, ?)",
                (name, pay_rate),
            ).lastrowid
        except sq.IntegrityError:
            raise TimeTrackerError(f"Client '{name}' already exists.") from None

        assert client_id is not None
        for alias in [name, *(aliases or [])]:
            _insert_client_alias(conn, client_id, alias)

    return client_id


def edit_client(
    conn: sq.Connection,
    client_id: int,
    new_name: str | None = None,
    pay_rate: float | None = None,
    aliases: list[str] | None = None,
):
    """
    Renames a client, changes its rate, and/or adds aliases.

    A new rate cascades to every project whose rate still equals the client's
    old rate. Projects with their own rate are left alone. A rename keeps the
    old name as an alias so existing habits and scripts keep working.
    """
    _check_rate(pay_rate)

    with conn:
        if new_name:
            try:
                conn.execute(
                    "UPDATE clients SET client_name = ? WHERE client_id = ?",
                    (new_name, client_id),
                )
            except sq.IntegrityError:
                raise TimeTrackerError(f"Client '{new_name}' already exists.") from None

            # The new name may already be one of this client's aliases,
            # e.g. promoting an abbreviation to the real name
            owner = conn.execute(
                "SELECT client_id FROM client_alias WHERE client_alias_text = ?",
                (new_name,),
            ).fetchone()
            if owner is None:
                _insert_client_alias(conn, client_id, new_name)
            elif owner[0] != client_id:
                raise TimeTrackerError(
                    f"'{new_name}' is already an alias of {_client_name(conn, owner[0])}."
                )

        if pay_rate is not None:
            old_rate = conn.execute(
                "SELECT pay_rate_hourly FROM clients WHERE client_id = ?", (client_id,)
            ).fetchone()[0]

            # IS rather than = so a client going from no rate to a rate also
            # updates projects that inherited "no rate"
            conn.execute(
                "UPDATE projects SET pay_rate_hourly = ? "
                "WHERE client_id = ? AND pay_rate_hourly IS ?",
                (pay_rate, client_id, old_rate),
            )
            conn.execute(
                "UPDATE clients SET pay_rate_hourly = ? WHERE client_id = ?",
                (pay_rate, client_id),
            )

        for alias in aliases or []:
            _insert_client_alias(conn, client_id, alias)


def _insert_client_alias(conn: sq.Connection, client_id: int, alias: str):
    try:
        conn.execute(
            "INSERT INTO client_alias (client_alias_text, client_id) VALUES (?, ?)",
            (alias, client_id),
        )
    except sq.IntegrityError:
        owner = resolve_client(conn, alias)
        assert owner is not None
        raise TimeTrackerError(
            f"'{alias}' is already used by client {_client_name(conn, owner)}."
        ) from None


def list_clients(conn: sq.Connection) -> list[sq.Row]:
    """Every client with its rate and aliases (excluding its own name)."""
    return conn.execute(
        """
        SELECT c.client_id, c.client_name, c.pay_rate_hourly,
            GROUP_CONCAT(a.client_alias_text, ', ') AS aliases
        FROM clients AS c
        LEFT JOIN client_alias AS a
            ON a.client_id = c.client_id AND a.client_alias_text <> c.client_name
        GROUP BY c.client_id
        ORDER BY c.client_name
        """
    ).fetchall()


# --- Projects ---


def create_project(
    conn: sq.Connection,
    client_id: int,
    name: str,
    pay_rate: float | None | _Unset = UNSET,
    aliases: list[str] | None = None,
) -> int:
    """
    Creates a project under a client. With the rate UNSET, the project copies
    the client's current rate and follows future client rate changes. Passing
    None explicitly means the project has no rate.
    """
    if isinstance(pay_rate, _Unset):
        pay_rate = conn.execute(
            "SELECT pay_rate_hourly FROM clients WHERE client_id = ?", (client_id,)
        ).fetchone()[0]
    else:
        _check_rate(pay_rate)

    with conn:
        try:
            project_id = conn.execute(
                "INSERT INTO projects (project_name, client_id, pay_rate_hourly) "
                "VALUES (?, ?, ?)",
                (name, client_id, pay_rate),
            ).lastrowid
        except sq.IntegrityError:
            raise TimeTrackerError(
                f"Project '{name}' already exists for {_client_name(conn, client_id)}."
            ) from None

        assert project_id is not None
        for alias in [name, *(aliases or [])]:
            _insert_project_alias(conn, project_id, client_id, alias)

    return project_id


def edit_project(
    conn: sq.Connection,
    project_id: int,
    new_name: str | None = None,
    pay_rate: float | None | _Unset = UNSET,
    aliases: list[str] | None = None,
):
    """
    Renames a project, changes its rate, and/or adds aliases. Leaving the
    rate UNSET keeps it unchanged, and None clears it.
    """
    client_id = conn.execute(
        "SELECT client_id FROM projects WHERE project_id = ?", (project_id,)
    ).fetchone()[0]

    with conn:
        if new_name:
            try:
                conn.execute(
                    "UPDATE projects SET project_name = ? WHERE project_id = ?",
                    (new_name, project_id),
                )
            except sq.IntegrityError:
                raise TimeTrackerError(
                    f"Project '{new_name}' already exists for "
                    f"{_client_name(conn, client_id)}."
                ) from None

            owner = conn.execute(
                "SELECT project_id FROM project_alias "
                "WHERE client_id = ? AND project_alias_text = ?",
                (client_id, new_name),
            ).fetchone()
            if owner is None:
                _insert_project_alias(conn, project_id, client_id, new_name)
            elif owner[0] != project_id:
                raise TimeTrackerError(
                    f"'{new_name}' is already an alias of another project for "
                    f"{_client_name(conn, client_id)}."
                )

        if not isinstance(pay_rate, _Unset):
            _check_rate(pay_rate)
            conn.execute(
                "UPDATE projects SET pay_rate_hourly = ? WHERE project_id = ?",
                (pay_rate, project_id),
            )

        for alias in aliases or []:
            _insert_project_alias(conn, project_id, client_id, alias)


def _insert_project_alias(
    conn: sq.Connection, project_id: int, client_id: int, alias: str
):
    try:
        conn.execute(
            "INSERT INTO project_alias (project_alias_text, project_id, client_id) "
            "VALUES (?, ?, ?)",
            (alias, project_id, client_id),
        )
    except sq.IntegrityError:
        raise TimeTrackerError(
            f"'{alias}' is already used by another project for "
            f"{_client_name(conn, client_id)}."
        ) from None


def list_projects(conn: sq.Connection, client_id: int | None = None) -> list[sq.Row]:
    """Every project (optionally for one client) with its rate and aliases."""
    query = """
        SELECT p.project_id, c.client_name, p.project_name, p.pay_rate_hourly,
            GROUP_CONCAT(a.project_alias_text, ', ') AS aliases
        FROM projects AS p
        JOIN clients AS c ON c.client_id = p.client_id
        LEFT JOIN project_alias AS a
            ON a.project_id = p.project_id AND a.project_alias_text <> p.project_name
    """
    params: tuple = ()
    if client_id is not None:
        query += " WHERE p.client_id = ?"
        params = (client_id,)
    query += " GROUP BY p.project_id ORDER BY c.client_name, p.project_name"

    return conn.execute(query, params).fetchall()
