# Time Tracker Brainstorming

This applications is designed to help me track time for work, and output a structured PDF report at given time intervals. 
The app will be a simple CLI that allows me to clock in, clock out, and generate reports.

This brainstorming note will document the various features and functionality so I can think through how to code this.

## Clock in / Clock out

The app should allow me to clock in and out using the CLI. The commands are:

- `tt in` to clock in
- `tt out --id <id>` to clock out
- `tt add` to log a whole finished entry at once
- `tt edit <id>` to correct an entry
- `tt delete <id>` to remove one
- `tt status` to see what's open

They share these flags:
- Manual start/end time `--time HH:MM(:SS)` (`in` and `out`), optionally after a date: `--time "2026-09-21 23:50"`
- On adding a whole entry rather than just clocking in and out, `--start-time` and `--end-time` (`add` and `edit`)
- Client `--client "TechForce Advisors"`
- Project `--project "TF Pro Forma"`
- Description `--desc "Finished successfully testing on the test deployment and stood up to production"`
- Synchronous logging `--watch` (clock in only)
- ID `--id 1` (clock out only)

Time will be tracked in a SQLite database in this format:

| Log ID | Start Time | End Time | Client ID | Project ID | Description | Pay Rate Hourly | Total Pay |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-01 08:23:25 | 2026-09-01 13:17:53 | 3 | 7 | Finished successfully... | 35 | 171.77 |

Start and end are shown here in local time so the example reads clearly, but they are
stored as UTC epoch seconds. Client ID and Project ID are integer foreign keys rather
than names. The total is the duration in seconds over 3600, times the hourly rate,
rounded to cents.

Most of the flags directly feed into the database. If start or end are left empty, the current time is substituted on the current command. If client, project, or description are left empty, the database will leave them empty. A project on its own is enough, since it implies its client, as long as the project name isn't shared by more than one client. When it is, `--client` is required.

If watch is included as a flag, the tracker runs synchronously and shows a continuously incrementing counter. Pressing Enter clocks out and asks for an optional description to append. Pressing Ctrl+C stops the counter and leaves the entry running.
The full TUI for the counter will be a later feature. It should include a live editor for client, project, and description, including a box to type the description into while the timer is running.

When a user clocks in, the system should output the ID of the time entry they began, so that if the user needs to manually edit or update that time entry later, they can use the ID that is output.

We should also have an edit command that accepts an entry ID as the first argument, and then follows the same flags as above (using `--start-time` and `--end-time` to correct time) and the other flags as above for correcting clients, projects, and descriptions. On edit, `--desc` replaces the description instead of appending. Edit also has flags for things the other flags can't express:
- `--no-client` removes the client, and with it the project
- `--no-project` removes the project and keeps the client
- `--no-desc` removes the description
- `--reopen` clears the end time, for undoing an accidental clock out
- `--refresh-rate` looks up the entry's rate again from its current project or client

The pay rate hourly inherits from the project, or from the client when the entry has no project. It's copied onto the entry so that reports generated after a pay rate changes still reflect the actual pay rate at the time of the work entry. The rate is taken when the entry is clocked out (or closed by an edit), so a rate set while the entry is open still applies. After that it only changes when the entry's client or project changes, or when `--refresh-rate` is used. Closed entries are never updated automatically when a project's rate changes.

Also a delete command that accepts an entry ID and deletes the entire entry from the database. It shows the entry and asks for confirmation first, and `--yes` skips the question.

Another important feature is a `status` command that allows the user to see whether they are currently clocked in or clocked out, and if they are clocked in, it will show them which session(s) they are logged in to.

### Edge Cases

| Case | Issue | How to Handle |
|---|---|---|
| Clocks out with different client/project than clocking in | Writing new one to the db will overwrite previous client/project | Leave alone--make sure this is documented so users know that writing a new client/project over an existing entry will update the existing entry. The pay rate is looked up again for the new client/project. |
| Changes the client, but not the project, on clock out or edit | The old project belongs to the old client, so the entry would point at another client's project | Clear the project. In an interactive terminal, list the new client's projects and let the user pick one by number or name, or press Enter for none. The database also enforces that an entry's project belongs to its client. |
| Clocks out with different description than clocking in | Writing new one will overwrite previous description | Append instead, separated by a blank line (`\n\n`), and document. This allows users to write what they started working on initially, and then add to it later. The edit command replaces descriptions instead of appending. |
| Provides an end time before the start time | Time tracking will have errors and not be accurate | Throw an error, require user to correct start and/or end time manually |
| User puts in a missing ID | Doesn't match to anything | Throw error, don't write anything |
| A session spans past midnight for one or more days | An entry is a single start and end timestamp, so it has no one calendar day it belongs to | Allow the session to span multiple days, just as logged, in the database. We only handle this on report generation, when we show the time for a day and break it up for the report generation. |
| Time is after the present time | Would write into the future | Should block--not a syntax error, but semantics. Can't log time in the future. |
| Clock in while already clocked in | Conflicts with currently open time entry | Give a warning and clock in anyway. Allows user to correct if they forgot to clock out without messing up current clock in, and also can allow multiple clock ins if working on multiple projects simultaneously |
| Clock out while nothing is open | Can try to close a clocking out session that's not open | Throw error. Clocking out manually (not from the TUI) should require an ID. No sense in trying to start a new session--they can just log a new session with both times, rather than trying to clock out. Without `--id`, the error lists the IDs of any open entries. |
| Clock out of an entry that's already closed | Would silently change its end time | Throw error, and point to `tt edit <id> --end-time` for changing the end time |
| Overlapping entries when backfilling by hand | Multiple entries can overlap in time | Allow it, but show alert to user. This functionality should be allowed, but shouldn't always be assumed to be intentional. Back-to-back entries (one ends as the next starts) don't overlap. An open entry counts as running indefinitely. Edits only check for overlaps when they change the entry's times. |
| DST Transitions | Duration will be off by one hour | Store UTC time codes so that DST doesn't affect calculations |
| Typed local time falls on a DST change | Converting to UTC needs a guess: a spring-forward time like 02:30 doesn't exist, and a fall-back time like 01:30 happens twice | Use the later real time for a missing time and the first occurrence for a repeated one, and print a warning saying which time was used |
| Invalid time like `25:00`, `12:60`, or `2026-02-30` | Not a real time | Throw error |
| Misspelling of client or project | Could create a new, distinct client or project | Should require manual creation of new client or project and then throw error on a misspelling. Aliases catch abbreviations, and names match case-insensitively |
| Project name shared by more than one client | `--project Website` could mean either | Throw error asking for `--client`, even on an edit where the entry already has a client |
| User manually clocks time in HH:MM format for a session that began on a previous day | Ambiguous whether time is today, or the day the session started | Assume current day, allow `--time` flag to accept a time string that includes a date, and if it doesn't, then assume the date defaults to current date. If a dateless time lands in the future (e.g. `--time 23:50` typed at 00:30), the error suggests the dated form for yesterday. |
| Traveling or relocating across time zone | Which local day an entry falls on can shift | Accepted, durations come from UTC and never change. Display and day/week/month grouping use the machine's local zone at run time, so running the same report from a different time zone can move an entry across a day boundary. If this becomes a problem, we'll add a fixed home time zone to the User table and convert against that instead. |
| Deleting an entry that appears on an issued invoice | The invoice's contents would silently change, so it could no longer be reproduced to match what was sent | Block the delete and throw an error naming the invoice. The user can void that invoice first if they really need to remove the entry. Deleting an entry that only appears on drafts is fine, since drafts bill nothing. |
| Editing an entry that appears on an issued invoice | Same as deleting: the sent invoice would no longer match | Block the edit and throw an error naming the invoice. Void the invoice first. |
| Reopening an entry that's on any invoice, including a draft | Invoices can only contain finished entries | Block it. Delete the draft first. |
| Entry logged while its project had no rate | The entry keeps no rate even after the project gets one | Open entries pick up the new rate at clock out. Closed entries are left alone, and `tt edit <id> --refresh-rate` updates one on request. |

## Report Generation

Report generation should allow the user to display/generate a report given certain criteria or flags. For example, they should be able to generate a report for a given client or list of clients, project or list of projects, given time frame, and should have the option to view the report by entry, day, week, or month. The user should also be able to list all clients, list all projects, list all projects for a given client. The user should also be able to choose which fields are included, and the default is all fields. Typically, the start and end times will collapse into a summation of the durations *unless* the user has selected to view the report by entry rather than by day, week, or month.

The command is `tt report`. With no dates, it covers the current week (Monday through Sunday). With only `--start`, it runs through today, and with only `--end`, it has no lower bound. `--end` is inclusive. An entry belongs to the range it *starts* in, even if it runs past the end, matching how invoices bill whole entries. Plain reports include billed entries. Only `--invoice` excludes them by default.

When grouping by day, week, or month, each row is one period across everything that was filtered, so the past week grouped by week is one row. Filter with `--client` or `--project` to see one client's time. Weeks start on Monday. Periods with no work get no row.

All grouping and display converts stored UTC timestamps into the machine's local timezone at run time. Day, week, and month boundaries, including the midnight split for multi-day sessions, are local boundaries, not UTC ones.

If the user groups by something other than entry and requests fields that can't be grouped like ID or description, the result should return a list of IDs (and of clients and projects) and should concatenate the descriptions. For example, if I ask for the past week, grouped by week, then I should get one result, showing the total time for the week, either without IDs or a list, and then showing plain text descriptions all appended together. Ideally the descriptions for each session should be separated by `\n\n` so that there's an empty line between each entry, though for certain formats this might backfire, such as a table, since it will not create a new line within the table, but rather create a new line out of the table and mess up the formatting. This is handled per format:
- Terminal table: multi-line cells, so the blank lines are kept
- Markdown: newlines become `<br>`, and `|` is escaped as `\|`
- CSV: the cell is quoted, which spreadsheets read as a multi-line cell
- TSV: newlines and tabs are escaped as `\n` and `\t`, so every line is exactly one row
- JSON: kept as real newlines in the string

Fields that only make sense per entry (`start`, `end`, `rate`) can't be requested when grouping. Asking for them gives an error. Grouped reports always include the period as their first column.

A session that crosses a period boundary (midnight for days) is split into pieces by local time. Its pay is divided between the pieces in proportion to time, in whole cents, so the pieces always add back up to the entry's exact total.

Open entries (still clocked in) are left out of reports and invoices, since they have no end time or pay yet. The report says how many were skipped, e.g. "1 open entry not included". The database also refuses to link an open entry to an invoice.

One note on the PDF/Excel specifically: The user may want to create a full invoice from this, complete with address, invoice numbers, title, formatting, and more. The User table stores this. `tt setup` asks for it (and for where the database lives), `tt user show` displays it, and `tt user edit --city Orem` changes one field. Name, street address, city, state, and ZIP are required. Address line 2, email, phone, and payment notes are optional and are left off the invoice when blank. 
The invoice layout follows the template in `docs/invoice-example/`: an "HOURLY INVOICE" title with the billing period, the invoice number at the top right, the user's name and address as the sender, and the client's name (no client address is stored). Line items are one row per project per day, for days with work only, with Date, Project, Hours, Amount, and Description columns, then a Total row. Each row's amount uses that project's rate, since projects on one invoice can have different rates. The billing period is stored on the invoice so a regenerated invoice shows the same title even when the first or last days had no work.

Invoices generated should display times as `4:53:12` rather than `4.89` even though `4.89` is what should be used in pay calculations. Time should be measured in seconds, not rounded to minutes. In the past I used a spreadsheet that had a column for `4:53:12` and then a conversion column that turned it into `4.89` to do the math, but this is unnecessary--no rounding to decimals required, we can convert `4:53:12` raw into a float and calculate dollar amounts, rounded to cents, after that.

Another note on invoices: each individual entry will be populated with its hourly pay rate, inherited from the project *at the time of the entry* so that changing pay rates per project or client won't cause invoices to have the wrong pay rate.

For the outputs, PDF and Excel will need to automatically be written to disc. Invoices should be specifically put in a new directory, with a filename that contains the invoice number, user name, date, and client name.
Even though only issued invoices have an invoice number, drafts should be populated with an invoice number based on incrementing so the files are generated and are ready-to-send, and then the database is updated with the invoice number once it is sent. If multiple drafts are created, they will all still contain the same invoice number.
A single invoice covers exactly one client. Multi-client filters remain valid for reports, but `--invoice` requires the selection to resolve to one client.

Markdown, JSON, CSV, and TSV can all be printed to the terminal, but should optionally be saved to disc by using a flag. `--write` saves to a `reports/` folder next to the database, with a default name like `report-2026-09-21-to-2026-09-27-by-day.csv`. `--filename` implies `--write`. A bare file name goes in `reports/`, and a name with a folder in it is used as given. The terminal table can only be printed, not saved; use `md` instead.

Generating an invoice creates it with status draft and links its entries. Drafts can be regenerated freely and do not mark anything as billed. Issuing a draft sets a status to issued, which is the point at which its entries count as billed and become excluded from future invoices by default.
Regenerating an invoice reads its entries through invoice entries rather than rerunning the original filters, so a regenerated invoice always matches the one that was issued.

The report should be able to return in the following formats:
- PDF
- Excel spreadsheet
- Terminal table (`table`, the default)
- Markdown table (`md`)
- JSON output
- CSV
- TSV

Given these requirements, we should have these flags:
- Client `--client "TechForce Advisors" [--client "Patea LLC"]`
- Project `--project "TF Proforma" [--project "Wedding Platform"]`
- Start date `--start 2026-09-01`
- End date `--end 2026-09-30`
- Output format `--output table` / `md` / `json` / `csv` / `tsv` (built), `pdf` / `xlsx` (with invoices)
- Fields `--fields id,client,project,duration`. Per entry: `id, start, end, client, project, description, duration, rate, pay`. Grouped: `period, id, client, project, description, duration, pay`
- Group by `--group-by entry|day|week|month`
- Invoice t/f `--invoice` (not built yet)
- Include billed t/f `--include-billed` (not built yet) (an entry counts as billed once it is linked to an issued invoice, so entries sitting only on drafts are never excluded)
- Write to disc `--write`
- Filename override `--filename 2026-09-01-hours-logged.csv`

### Invoice commands

Generating a draft is part of report generation via `--invoice`, but the rest of the
invoice lifecycle needs its own commands, since issuing is what actually marks entries
as billed:

A draft is created with `tt report --invoice`, using the same filters as any report. The selection has to resolve to one client, and entries already on an issued invoice are left out unless `--include-billed` is passed. The file is written as PDF by default, or `--output xlsx` for the spreadsheet. If the file can't be written, the draft is removed again rather than left behind.

- List invoices `tt invoice list` — shows ID, number (or the predicted one if still a draft), client, period, status, hours, and total. This is how you find the ID to issue.
- Issue a draft `tt invoice issue <invoice id>` — allocates the client's next invoice number, sets status to issued, and regenerates the file with the confirmed number.
- Void an issued invoice `tt invoice void <invoice id>` — sets status to void, which releases its entries to be billed again while the invoice keeps its number so the client's sequence stays gapless.
- Delete a draft `tt invoice delete <invoice id>` — only permitted while status is draft, since drafts hold no number and bill nothing.
- Write the file again `tt invoice regenerate <invoice id> [--output pdf|xlsx]` — rebuilds from the invoice's linked entries, not the original filters.

Void and delete ask for confirmation, and `--yes` skips it.

### Edge Cases

| Case | Issue | How to Handle |
| --- | --- | --- |
| Client/project doesn't exist | The selection will be empty or not contain some from the given client/project | Allow it to be missing, don't flag or warn. A filter made only of unknown names returns nothing, not everything. |
| Project name shared by more than one client | `--project Website` could mean either | Include every matching project, narrowed to the `--client` filter if one is given. Unlike clocking, reports don't need an unambiguous name. |
| Entry runs past the end of the range | It could count in either range | It belongs to the range it starts in. Grouped by day, its after-midnight piece still shows as its own day, even past `--end`. |
| Open entries match the filters | They have no end time or pay | Leave them out and print a warning saying how many were skipped |
| Start date is after end date | Filters out everything | Allow selection to be empty |
| Either date is after the present | Filters out some things | Allow selection to be empty |
| Filters on an invoice include entries already billed for | Risks double-billing time entries | Default to excluding them, add flag to manually include, such as in cases of invoice regeneration when billing did not actually occur. Regenerating an existing invoice looks up its entries through the invoice entries table rather than re-running the original filters, so a regenerated invoice always matches the one that was sent. |

## Client and Project Creation

Since there are likely multiple clients, and potentially multiple projects per client, we should be able to manage the clients and the projects. These primarily have names, though each client and potentially project can have a billable rate as well. When a new project is created, the client's rate is automatically copied over unless a project override is explicitly given. Changing a client's rate cascades to projects still holding the old value.

Because commands accept a client by name or by alias in the same argument position, an alias has to be unique against client names as well as against other aliases. Otherwise an alias like `G8` could refer both to an abbreviation of G8 Capital and to a different client actually named G8, and the command would have no way to tell which was meant. The same rule applies to project aliases within a client. Creating an alias that collides should throw an error rather than resolve to a guess.

Having one or more aliases begs for another table where many aliases join to one foreign client id.

Names and aliases match case-insensitively, so `tfa` finds `TFA`, and the two count as a collision. Project names and aliases only need to be unique within their client, so two clients can each have a "Website" project.

The commands are `tt client add|edit|list` and `tt project add|edit|list`.

### Create new Client

Accepts client name as a string as the first argument without flags, adds optional flags.

When a new client is created, the client details are all added to the client table, and then the initial client name that's passed in is also added to the client alias table so that we can search for the client ID from the alias table using any alias including the original name.

Flags:
- Alias `--alias TFA` (also accepted as `--client-alias`), repeat for several
- Billable rate `--pay-rate-hourly 35`

### Edit Client

Should always pass in client name/alias as the first argument without flags, or the client ID with `--id` instead. When a new pay rate is given, it cascades to all projects that currently have the same pay rate as the client (including projects with no rate, when the client had none). Projects that have a different pay rate will be left alone. Because the match is by value, a project deliberately set to the same rate as the client follows the client too. A client's rate can be changed but not removed.

Renaming a client keeps the old name as an alias, so old commands and habits keep working. That also means the old name can't be reused for a different client.

Flags:
- client ID (alternative to name) `--id 123`
- New name `--new-client "G8 Capital"`
- New rate `--pay-rate-hourly 40`
- New alias `--alias G8`

### Create new project

Should always pass in client name/ID/alias as the first argument without flags, and second argument as project name without flags, adds optional flags.

When a new project is created, the project details are all added to the project table, and then the initial project name that's passed in is also added to the project alias table so that we can search for the project ID from the alias table using any alias including the original name.

If no pay rate is given, then the pay rate defaults to that of the client, and then the project received inherited pay rate updates as the client receives them. If a different pay rate is passed (even if it is `None`, meaning no pay rate) then that will be set as the project pay rate. A project whose pay rate differs from teh client's old rate will be left alone when the client rate updates.

Flags:
- Pay rate for the project `--pay-rate-hourly 45`
- Explicitly no pay rate `--no-pay-rate`, so the project doesn't inherit the client's
- Alias `--alias TFPF`

### Edit project

Pass the client name/alias and then the project name/alias as the first two arguments.

Flags:
- New name `--new-project "TF Pro Forma v2"` (the old name stays as an alias)
- New rate `--pay-rate-hourly 50`, or remove it with `--no-pay-rate`
- New alias `--alias PF2`

### List

`tt client list` shows every client with its rate and aliases. `tt project list [client]` shows projects, optionally for one client.

## Package and DB management

The database will live at `~/TimeTracker/timetracker.db` by default, but the user can choose a different location during setup. The choice will be stored in a config file at `~/.config/timetracker/config.toml`, as `db_path = "..."`, instead of an environment variable.

The path resolves according to this preference: an explicit argument passed in code, then the `TIMETRACKER_DB` environment variable, then the configured location, then the default. Tests pass an explicit path so they don't use the real data.

The directory will be created the first time it's used rather than at install time. The setup command will also create it, but any command that opens the database will create it if it's not there.
