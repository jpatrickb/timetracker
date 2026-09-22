# Project Map

Functionality is broken up by module. Items marked *(planned)* aren't built yet.

- `db.py`: database operations
    - resolve the database path (argument, `TIMETRACKER_DB`, config file, default)
    - connect, creating the directory and applying migrations
    - `connection()` context manager that always closes
- `clients.py`: client and project management
    - resolve a client or project by name or alias
    - create/edit client (name, pay rate with cascade, aliases)
    - create/edit project (name, pay rate, aliases)
    - list clients, list projects
- `clock.py`: time logging
    - parse typed times (with DST warnings) and format timestamps/durations
    - clock in, clock out, add a finished entry
    - edit (including clearing fields, reopening, refreshing the rate), delete
    - open entries, overlap detection, invoice-link checks
- `user.py`: the single user row behind the invoice sender block
- `invoice.py`: invoice lifecycle
    - create a draft and link its entries
    - issue (allocating the client's next number), void, delete a draft
    - build the document a renderer needs: one row per project per day
    - invoice file names
- `tui.py`: the `--watch` full-screen view (Textual)
    - live wall clock, elapsed time, and earnings
    - editable client/project/start, description editor with autosave
    - today's entries, detach or clock out
- `cli.py`: the `tt` command-line interface over the modules above
- `errors.py`: `TimeTrackerError`, for user-facing errors shown without a traceback
- `report.py`: reporting
    - filter entries by client, project, and date range (skipping open entries)
    - group by entry/day/week/month, splitting sessions at local period boundaries
    - divide pay across split pieces in whole cents
- `formats/`: output formats
    - `__init__.py`: shared headers, value formatting, total row, default filename
    - `table.py`: terminal table and Markdown
    - `delimited.py`: CSV and TSV
    - `json_format.py`: JSON
    - `xlsx.py`: invoice and report as Excel workbooks (openpyxl)
    - `pdf.py`: invoice and report as PDFs, typeset with Typst
- Invoice management *(planned)*
    - generate draft, issue, void, delete draft

## Files

```
time-tracker/
├── dev
│   └── dev.db                 # `make init-db` rebuilds it
├── docs
│   ├── brainstorm.md          # spec and edge cases
│   ├── invoice-example/       # the spreadsheet the invoice layout follows
│   ├── docs.md                # command reference
│   ├── map.md
│   └── schema.md
├── makefile
├── pyproject.toml
├── README.md
├── src
│   └── timetracker
│       ├── __init__.py
│       ├── cli.py
│       ├── clients.py
│       ├── clock.py
│       ├── db.py
│       ├── errors.py
│       ├── invoice.py
│       ├── user.py
│       ├── formats
│       │   ├── __init__.py
│       │   ├── delimited.py
│       │   ├── json_format.py
│       │   ├── pdf.py
│       │   ├── table.py
│       │   └── xlsx.py
│       ├── migrations
│       │   └── 001_initial.sql
│       ├── report.py
│       └── tui.py
├── tests
│   ├── test_clients.py
│   ├── test_clock.py
│   ├── test_db.py
│   ├── test_invoice.py
│   ├── test_report.py
│   └── test_tui.py
└── uv.lock
```

## Live Production Map

Standard path is `~/TimeTracker/` for the actual data files and reports, as follows:

```
TimeTracker/
├── timetracker.db
├── invoices/
│   ├── techforce-advisors-2026-09-01-2026-09-14-hourly-invoice-patrick-beal-no-12.pdf
├── reports/
│   ├── report-2026-09-21-to-2026-09-27-by-day.csv
```

The database location comes from `~/.config/timetracker/config.toml` (set by `tt setup`), and the `invoices/` and `reports/` folders sit next to whichever database is in use.
