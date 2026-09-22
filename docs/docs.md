# Documentation

Command reference for `tt`. Every command also has `--help`.

Errors caused by input, like an unknown client or a time in the future, print one red line and exit with status 1. Warnings, like overlapping entries, print in yellow and don't stop the command.

## Times

Time flags take `HH:MM` or `HH:MM:SS` in the machine's local time zone, optionally after a date: `09:15`, `9:15:30`, `"2026-09-21 23:50"`. Without a date, today is assumed. Times can't be in the future.

On a daylight saving change, a time that doesn't exist (e.g. 02:30 when clocks spring forward) becomes the next real time, and a time that happens twice (e.g. 01:30 when clocks fall back) uses the first one. Either way a warning shows the time that was used.

## Clients

```
tt client add NAME [--alias A]... [--pay-rate-hourly R]
tt client edit NAME | --id N  [--new-client NAME] [--pay-rate-hourly R] [--alias A]...
tt client list
```

- Names and aliases match case-insensitively and must be unique across all clients.
- A new client rate also updates every project still on the client's old rate.
- Renaming keeps the old name as an alias.

## Projects

```
tt project add CLIENT NAME [--pay-rate-hourly R | --no-pay-rate] [--alias A]...
tt project edit CLIENT PROJECT [--new-project NAME] [--pay-rate-hourly R | --no-pay-rate] [--alias A]...
tt project list [CLIENT]
```

- Without a rate flag, a new project inherits the client's rate and follows it when the client's rate changes.
- Project names and aliases only need to be unique within their client.

## Time entries

```
tt in [--time T] [--client C] [--project P] [--desc D] [--watch]
tt out --id N [--time T] [--client C] [--project P] [--desc D]
tt add --start-time T --end-time T [--client C] [--project P] [--desc D]
tt edit N [--start-time T] [--end-time T] [--client C] [--project P] [--desc D]
          [--no-client] [--no-project] [--no-desc] [--reopen] [--refresh-rate]
tt delete N [--yes]
tt status
```

**Client and project.** A `--project` alone implies its client. If more than one client has a project with that name, `--client` is required. Changing an entry's client without giving a project clears a project that belonged to the old client. In a terminal you're then offered the new client's projects to pick from.

**Descriptions.** `tt out --desc` appends to the existing description after a blank line. `tt edit --desc` replaces it, and `--no-desc` removes it.

**Pay rate.** Entries take the project's rate, or the client's if there's no project. The rate is looked up at clock-out, so a rate set while you're clocked in applies. Changing a closed entry's client or project looks the rate up again. Otherwise it stays as logged unless you pass `--refresh-rate`.

**Overlaps.** Overlapping entries are allowed, with a warning, including clocking in while already clocked in. An open entry counts as running indefinitely. Back-to-back entries don't overlap.

**`--watch`.** Shows a running timer. Enter clocks out and asks for an optional description to append. Ctrl+C leaves the entry running.

**Invoices.** Entries on an issued invoice can't be edited or deleted until that invoice is voided. Entries on any invoice, draft included, can't be reopened.

**`tt out` without `--id`** lists the IDs of open entries. **`tt delete`** shows the entry and asks before deleting, and `--yes` skips the question.

## Reports

```
tt report [--client C]... [--project P]... [--start YYYY-MM-DD] [--end YYYY-MM-DD]
          [--group-by entry|day|week|month] [--fields a,b,c]
          [--output table|md|json|csv|tsv] [--write] [--filename NAME]
```

- **Range.** Defaults to this week, Monday through Sunday. `--start` alone runs through today. `--end` is inclusive. Entries count toward the range they start in.
- **Filters.** Names and aliases work. Unknown names match nothing, with no error. A project name several clients share matches all of them unless `--client` narrows it.
- **Grouping.** `entry` (the default) gives one row per entry. `day`, `week`, and `month` give one row per period, with lists of entries, clients, and projects, descriptions joined by blank lines, and totals. Sessions are split at local midnight (or week/month boundaries), and pay is divided in proportion.
- **Fields.** Per entry: `id, start, end, client, project, description, duration, rate, pay`. Grouped: `period, id, client, project, description, duration, pay`.
- **Output.** `table` prints to the terminal. `md`, `json`, `csv`, and `tsv` print plain text you can pipe, or save with `--write` to `reports/` next to the database. `--filename` picks the name, and a name with a folder in it is saved there instead. JSON gives times in ISO 8601 with the UTC offset, durations in seconds, and pay in dollars.
- **Open entries** are left out, with a warning saying how many.

## Configuration

The database location is chosen in this order:

1. `TIMETRACKER_DB` environment variable
2. `db_path` in `~/.config/timetracker/config.toml`
3. `~/TimeTracker/timetracker.db`

The directory is created on first use.

## Development

`make init-db` rebuilds `dev/dev.db` from the migrations. Use it with `TIMETRACKER_DB=dev/dev.db tt ...`. Run tests with `uv run pytest`.
