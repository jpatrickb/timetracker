# Time Tracker

Track billable time from the terminal and turn it into invoices.

```
$ tt in --project "TF Pro Forma" --desc "Reviewing the extraction pipeline"
Clocked in: entry 42 (TechForce Advisors / TF Pro Forma) at 2026-09-22 09:14:03

$ tt out --id 42 --desc "Shipped it"
Clocked out: entry 42 (TechForce Advisors / TF Pro Forma), 2:36:37

$ tt report --group-by day
$ tt report --start 2026-09-01 --end 2026-09-14 --invoice
```

## What it does

- **Clock in and out**, or log finished entries after the fact, with a client, project, and description.
- **A live view** (`--watch`): a wall clock, elapsed time, what you've earned so far, and a description box you can type in while the timer runs. Detach and re-attach without ending the entry.
- **Clients and projects** with aliases and hourly rates. A project inherits its client's rate and follows changes to it, unless it has its own.
- **Reports** filtered by client, project, and date, grouped by entry, day, week, or month, as a terminal table, Markdown, JSON, CSV, or TSV.
- **Invoices** as PDF or Excel, with per-client numbering, drafts, issuing, and voiding. Issued invoices can't be quietly changed: their entries are locked against edits and deletes until the invoice is voided.

Everything is stored in one SQLite file, with times kept as UTC so daylight saving changes never alter a duration.

## Install

```
uv tool install --editable .
```

That puts `tt` on your PATH. Then set up your details, which invoices are built from:

```
tt setup
```

It asks where the database should live (`~/TimeTracker/timetracker.db` by default) and for the name and address that appear on invoices.

## Getting started

```
tt client add "TechForce Advisors" --alias TFA --pay-rate-hourly 35
tt project add TFA "TF Pro Forma" --pay-rate-hourly 45
tt in --project "TF Pro Forma"
tt status
tt out --id 1
```

Full command reference: [docs/docs.md](docs/docs.md).

## Documentation

| File | What's in it |
| --- | --- |
| [docs/docs.md](docs/docs.md) | Command reference |
| [docs/brainstorm.md](docs/brainstorm.md) | The spec, including every edge case and how it's handled |
| [docs/schema.md](docs/schema.md) | Database tables, constraints, and triggers |
| [docs/map.md](docs/map.md) | Which module does what |

## Development

```
uv sync            # install dependencies, including dev tools
uv run pytest      # run the tests
make init-db       # rebuild dev/dev.db from the migrations
```

Work against the development database with `TIMETRACKER_DB=dev/dev.db tt ...`, so the real one stays untouched.

Schema changes go in a new numbered file in `src/timetracker/migrations/`. Applied migrations are never edited: the app applies any missing ones when it opens the database, each in its own transaction.
