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

## Files

```
time-tracker/
├── docs
│   ├── brainstorm.md
│   ├── docs.md
│   ├── map.md
│   └── schema.md
├── pyproject.toml
├── README.md
├── src
│   └── timetracker
│       ├── __init__.py
│       ├── cli.py
│       ├── clock.py
│       ├── db.py
│       ├── formats
│       │   ├── __init__.py
│       │   ├── delimited.py
│       │   ├── pdf.py
│       │   ├── table.py
│       │   └── xlsx.py
│       ├── report.py
│       └── schema.sql
├── tests
└── uv.lock

```

