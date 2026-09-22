# Project Map

Functionality can be broken up as follows:

- Database operations
    - initialize database
    - add time entry
    - update time entry
    - get time entry/entries
- Time logging
    - clock in
    - clock out
    - update time entry
- Reporting
    - get data for report
    - format data
    - generate invoice (excel or pdf)
- Client management
    - Create client
    - Update client (name, pay rate)
    - Create alias
- Project management
    - Create project
    - Update project (name, pay rate)
    - Create alias
- Invoice Management
    - Generate invoice
    - Issue invoice
    - Void invoice
    - Delete invoice

## Files

```
time-tracker/
├── dev
│   └── dev.db
├── docs
│   ├── brainstorm.md
│   ├── docs.md
│   ├── map.md
│   └── schema.md
├── makefile
├── pyproject.toml
├── README.md
├── src
│   └── timetracker
│       ├── __init__.py
│       ├── __pycache__
│       │   ├── __init__.cpython-313.pyc
│       │   ├── cli.cpython-313.pyc
│       │   └── db.cpython-313.pyc
│       ├── cli.py
│       ├── clock.py
│       ├── db.py
│       ├── formats
│       │   ├── __init__.py
│       │   ├── __pycache__
│       │   │   └── table.cpython-313.pyc
│       │   ├── delimited.py
│       │   ├── pdf.py
│       │   ├── table.py
│       │   └── xlsx.py
│       ├── migrations
│       │   └── 001_initial.sql
│       └── report.py
├── tests
└── uv.lock
```

## Live Production Map

Standard path is `~/TimeTracker/` for the actual data files and reports, as follows:

```
TimeTracker/
├── timetracker.db
├── invoices/
│   ├── techforce-advisors-2026-09-01-2026-09-14-hourly-invoice-patrick-beal-no-12.pdf
```
