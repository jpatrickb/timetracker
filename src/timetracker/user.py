# user.py
#
# Author: Patrick Beal
#
# The single user_info row: who the invoices come from

import sqlite3 as sq

from timetracker.errors import TimeTrackerError

# Fields the user can set, and whether an invoice needs them
REQUIRED_FIELDS = (
    "first_name",
    "last_name",
    "address_line_1",
    "city",
    "state",
    "zip_code",
)
OPTIONAL_FIELDS = ("address_line_2", "email", "phone", "payment_notes")
FIELDS = (*REQUIRED_FIELDS, *OPTIONAL_FIELDS)

# The order `tt setup` asks in, which follows how an address is written
WIZARD_ORDER = (
    "first_name",
    "last_name",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "zip_code",
    "email",
    "phone",
    "payment_notes",
)

LABELS = {
    "first_name": "First name",
    "last_name": "Last name",
    "address_line_1": "Street address",
    "address_line_2": "Address line 2",
    "city": "City",
    "state": "State",
    "zip_code": "ZIP code",
    "email": "Email",
    "phone": "Phone",
    "payment_notes": "Payment notes",
}


def get_user(conn: sq.Connection) -> sq.Row | None:
    return conn.execute("SELECT * FROM user_info WHERE user_id = 1").fetchone()


def require_user(conn: sq.Connection) -> sq.Row:
    """The user row, or an error telling them to run setup."""
    user = get_user(conn)
    if user is None:
        raise TimeTrackerError(
            "Invoices need your name and address. Run `tt setup` first."
        )
    return user


def save_user(conn: sq.Connection, **values: str | None):
    """
    Creates or updates the single user row. Only the fields passed in change,
    so `tt user edit --city Provo` leaves everything else alone.
    """
    unknown = set(values) - set(FIELDS)
    if unknown:
        raise TimeTrackerError(f"Unknown field(s): {', '.join(sorted(unknown))}.")

    current = get_user(conn)
    merged = {f: (current[f] if current else None) for f in FIELDS}
    merged.update({k: v for k, v in values.items() if v is not None})

    missing = [LABELS[f] for f in REQUIRED_FIELDS if not merged[f]]
    if missing:
        raise TimeTrackerError(f"Still missing: {', '.join(missing)}.")

    columns = ", ".join(FIELDS)
    marks = ", ".join("?" * len(FIELDS))
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO user_info (user_id, {columns}) "
            f"VALUES (1, {marks})",
            [merged[f] for f in FIELDS],
        )


def full_name(user: sq.Row) -> str:
    return f"{user['first_name']} {user['last_name']}"


def address_lines(user: sq.Row) -> list[str]:
    """The address block for an invoice, skipping anything not filled in."""
    lines = [user["address_line_1"]]
    if user["address_line_2"]:
        lines.append(user["address_line_2"])
    lines.append(f"{user['city']}, {user['state']} {user['zip_code']}")
    for optional in ("email", "phone"):
        if user[optional]:
            lines.append(user[optional])
    return lines
