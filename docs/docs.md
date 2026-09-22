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

**`--watch` and `tt watch`.** `tt in --watch` opens a full-screen view over the entry; `tt watch [--id N]` re-attaches to an entry you're already clocked in to. Five panels: details, a wall clock, elapsed time and money earned, the description editor, and today's entries.

| Key | Does |
| --- | --- |
| `tab` | Move between panels |
| `enter` (in a detail field) | Apply the client, project and start time |
| `ctrl+s` | Save the description (it also autosaves every 15s) |
| `ctrl+d` | Detach, leaving the entry running |
| `ctrl+o` | Clock out |

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
- **Output.** `table` prints to the terminal. `md`, `json`, `csv`, and `tsv` print plain text you can pipe, or save with `--write` to `reports/` next to the database. `pdf` and `xlsx` always write a file. `--filename` picks the name, and a name with a folder in it is saved there instead. JSON gives times in ISO 8601 with the UTC offset, durations in seconds, and pay in dollars. The spreadsheet keeps dates, durations and money as real Excel values, so you can total or chart them.
- **Open entries** are left out, with a warning saying how many.

## Invoices

```
tt report --invoice [--client C] [--start D] [--end D] [--include-billed] [--output pdf|xlsx]
tt invoice list
tt invoice issue N [--output pdf|xlsx]
tt invoice void N [--yes]
tt invoice delete N [--yes]
tt invoice regenerate N [--output pdf|xlsx]
```

- **Creating one.** `tt report --invoice` makes a *draft* from the same filters a report uses, and writes the file to `invoices/` next to the database. The selection must be one client. Entries on an issued invoice are left out unless `--include-billed` is given, and open entries are always left out.
- **Rows.** One row per project per day, with Date, Project, Hours (`[h]:mm:ss`), Amount and Description, then a Total. A session crossing midnight is split, with its pay divided in proportion.
- **Numbers.** Each client has its own sequence. A draft shows the number it *would* get; the number is only recorded when you issue it. Voided invoices keep their number, so the sequence never repeats or skips.
- **Issuing** marks the entries as billed, which is what keeps them off later invoices, and writes the file again with the confirmed number. Billed entries can't be edited or deleted until the invoice is voided.
- **Regenerating** rebuilds from the invoice's linked entries, so it always matches what was sent, even if later entries would have matched the original filters.

## Your details

```
tt setup                  # database location, then name, address, and optional contact info
tt user show
tt user edit [--first-name X] [--last-name X] [--address X] [--address-2 X]
             [--city X] [--state X] [--zip X] [--email X] [--phone X] [--payment-notes X]
```

Name, street address, city, state and ZIP are required for invoices. Address line 2, email, phone and payment notes are optional, and blank ones are left off the invoice.

PDF output uses Typst and Excel uses openpyxl. Both install with the app.

## Tab completion

```
tt --install-completion      # once, then restart your shell
```

Beyond commands and flags, Tab completes values from your database:

| Where | Suggests |
| --- | --- |
| `--client`, and the client argument | Client names and aliases, with the full name as help |
| `--project`, and the project argument | Projects, narrowed to the client you already typed |
| `tt out --id`, `tt watch --id` | Open entries, with their client/project and start time |
| `tt edit`, `tt delete` | The 25 most recent entries, newest first |
| `tt invoice issue`/`delete` | Drafts only |
| `tt invoice void` | Issued invoices only |
| `--group-by`, `--output` | The valid choices |
| `--fields` | One column at a time, skipping ones you've already listed |

Completions open the database read-only, and return nothing rather than an error if it's missing or busy, so pressing Tab can never change your data.

## Configuration

The database location is chosen in this order:

1. `TIMETRACKER_DB` environment variable
2. `db_path` in `~/.config/timetracker/config.toml`
3. `~/TimeTracker/timetracker.db`

The directory is created on first use.

## Development

`make init-db` rebuilds `dev/dev.db` from the migrations. Use it with `TIMETRACKER_DB=dev/dev.db tt ...`. Run tests with `uv run pytest`.
