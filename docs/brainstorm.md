# Time Tracker Brainstorming

This applications is designed to help me track time for work, and output a structured PDF report at given time intervals. 
The app will be a simple CLI that allows me to clock in, clock out, and generate reports.

This brainstorming note will document the various features and functionality so I can think through how to code this.

## Clock in / Clock out

The app should allow me to clock in and out using the CLI, including flags such as:
- Manual start/end time `--time HH:MM(:SS)`
- On adding a whole entry rather than just clocking in and out, have a `--start-time` and `--end-time` flag.
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

Most of the flags directly feed into the database. If start or end are left empty, the current time is substituted on the current command. If client, project, or description are left empty, the database will leave them empty. If watch is included as a flag, then the tracker will run synchronously, showing a continuously incrementing counter, with a live editor for you to edit client, project, and description, with a place to log out.
The TUI for the counter will be a later feature--for now I'll just have a basic time display and allow it to wait for the user to reply.

When a user clocks in, the system should output the ID of the time entry they began, so that if the user needs to manually edit or update that time entry later, they can use the ID that is output.

We should also have an edit command that accepts an entry ID as the first argument, and then follows the same flags as above (using `--start-time` and `--end-time` to correct time) and the other flags as above for correcting clients, projects, and descriptions.

The pay rate hourly should inherit from the project, and be used to calculate the total pay once the time entry is completed and clocked out. This means that reports that are generated after a pay rate changes still reflect the actual pay rate at the time of the work entry.

Also a delete command that accepts an entry ID and deletes the entire entry from the database.

Another important feature is a `status` command that allows the user to see whether they are currently clocked in or clocked out, and if they are clocked in, it will show them which session(s) they are logged in to.

### Edge Cases

| Case | Issue | How to Handle |
|---|---|---|
| Clocks out with different client/project than clocking in | Writing new one to the db will overwrite previous client/project | Leave alone--make sure this is documented so users know that writing a new client/project over an existing entry will update the existing entry |
| Clocks out with different description than clocking in | Writing new one will overwrite previous description | Append instead, and document. This allows users to write what they started working on initially, and then add to it later. The update function will allow descriptions to be overwritten and replaced |
| Provides an end time before the start time | Time tracking will have errors and not be accurate | Throw an error, require user to correct start and/or end time manually |
| User puts in a missing ID | Doesn't match to anything | Throw error, don't write anything |
| A session spans past midnight for one or more days | An entry is a single start and end timestamp, so it has no one calendar day it belongs to | Allow the session to span multiple days, just as logged, in the database. We only handle this on report generation, when we show the time for a day and break it up for the report generation. |
| Time is after the present time | Would write into the future | Should block--not a syntax error, but semantics. Can't log time in the future. |
| Clock in while already clocked in | Conflicts with currently open time entry | Give a warning and clock in anyway. Allows user to correct if they forgot to clock out without messing up current clock in, and also can allow multiple clock ins if working on multiple projects simultaneously |
| Clock out while nothing is open | Can try to close a clocking out session that's not open | Throw error. Clocking out manually (not from the TUI) should require an ID. No sense in trying to start a new session--they can just log a new session with both times, rather than trying to clock out |
| Overlapping entries when backfilling by hand | Multiple entries can overlap in time | Allow it, but show alert to user. This functionality should be allowed, but shouldn't always be assumed to be intentional. |
| DST Transitions | Duration will be off by one hour | Store UTC time codes so that DST doesn't affect calculations |
| Misspelling of client or project | Could create a new, distinct client or project | Should require manual creation of new client or project and then throw error on a misspelling. Possibly add aliases to catch abbreviations |
| User manually clocks time in HH:MM format for a session that began on a previous day | Ambiguous whether time is today, or the day the session started | Assume current day, allow `--time` flag to accept a time string that includes a date, and if it doesn't, then assume the date defaults to current date. |
| Traveling or relocating across time zone | Which local day an entry falls on can shift | Accepted, durations come from UTC and never change. Display and day/week/month grouping use the machine's local zone at run time, so running the same report from a different time zone can move an entry across a day boundary. If this becomes a problem, we'll add a fixed home time zone to the User table and convert against that instead. |
| Deleting an entry that appears on an issued invoice | The invoice's contents would silently change, so it could no longer be reproduced to match what was sent | Block the delete and throw an error naming the invoice. The user can void that invoice first if they really need to remove the entry. Deleting an entry that only appears on drafts is fine, since drafts bill nothing. |

## Report Generation

Report generation should allow the user to display/generate a report given certain criteria or flags. For example, they should be able to generate a report for a given client or list of clients, project or list of projects, given time frame, and should have the option to view the report by entry, day, week, or month. The user should also be able to list all clients, list all projects, list all projects for a given client. The user should also be able to choose which fields are included, and the default is all fields. Typically, the start and end times will collapse into a summation of the durations *unless* the user has selected to view the report by entry rather than by day, week, or month.

All grouping and display converts stored UTC timestamps into the machine's local timezone at run time. Day, week, and month boundaries, including the midnight split for multi-day sessions, are local boundaries, not UTC ones.

If the user groups by something other than entry and requests fields that can't be grouped like ID or description, the result should abstain on returning the IDs (or return a list) and should concatenate the descriptions. For example, if I ask for the past week, grouped by week, then I should get one result, showing the total time for the week, either without IDs or a list, and then showing plain text descriptions all appended together. Ideally the descriptions for each session should be separated by `\n\n` so that there's an empty line between each entry, though for certain formats this might backfire, such as a table, since it will not create a new line within the table, but rather create a new line out of the table and mess up the formatting. We'll need to figure out how to handle this.

One note on the PDF/Excel specifically: The user may want to create a full invoice from this, complete with address, invoice numbers, title, formatting, and more. We'll need to create a table in the database to store some of these information, and have onboarding and update steps to input the information initially or update it later. 
Invoices generated should display times as `4:53:12` rather than `4.89` even though `4.89` is what should be used in pay calculations. Time should be measured in seconds, not rounded to minutes. In the past I used a spreadsheet that had a column for `4:53:12` and then a conversion column that turned it into `4.89` to do the math, but this is unnecessary--no rounding to decimals required, we can convert `4:53:12` raw into a float and calculate dollar amounts, rounded to cents, after that.

Another note on invoices: each individual entry will be populated with its hourly pay rate, inherited from the project *at the time of the entry* so that changing pay rates per project or client won't cause invoices to have the wrong pay rate.

For the outputs, PDF and Excel will need to automatically be written to disc. Invoices should be specifically put in a new directory, with a filename that contains the invoice number, user name, date, and client name.
Even though only issued invoices have an invoice number, drafts should be populated with an invoice number based on incrementing so the files are generated and are ready-to-send, and then the database is updated with the invoice number once it is sent. If multiple drafts are created, they will all still contain the same invoice number.
A single invoice covers exactly one client. Multi-client filters remain valid for reports, but `--invoice` requires the selection to resolve to one client.

Markdown, JSON, CSV, and TSV can all be printed to the terminal, but should optionally be saved to disc by using a flag.

Generating an invoice creates it with status draft and links its entries. Drafts can be regenerated freely and do not mark anything as billed. Issuing a draft sets a status to issued, which is the point at which its entries count as billed and become excluded from future invoices by default.
Regenerating an invoice reads its entries through invoice entries rather than rerunning the original filters, so a regenerated invoice always matches the one that was issued.

The report should be able to return in the following formats:
- PDF
- Excel spreadsheet
- Markdown table/terminal table
- JSON output
- CSV
- TSV

Given these requirements, we should have these flags:
- Client `--client "TechForce Advisors" [--client "Patea LLC"]`
- Project `--project "TF Proforma" [--project "Wedding Platform"]`
- Start date `--start 2026-09-01`
- End date `--end 2026-09-30`
- Output format `--output pdf` / `xlsx` / `table` / `json` / `csv` / `tsv`
- Fields `--fields id,client,project,duration`
- Group by `--group-by entry|day|week|month`
- Invoice t/f `--invoice`
- Include billed t/f `--include-billed` (an entry counts as billed once it is linked to an issued invoice, so entries sitting only on drafts are never excluded)
- Write to disc `--write`
- Filename override `--filename 2026-09-01-hours-logged.csv`

### Invoice commands

Generating a draft is part of report generation via `--invoice`, but the rest of the
invoice lifecycle needs its own commands, since issuing is what actually marks entries
as billed:

- List invoices `tt invoice list` — shows ID, number (or the predicted one if still a draft), client, status, and total. This is how you find the ID to issue.
- Issue a draft `tt invoice issue <invoice id>` — allocates the client's next invoice number, sets status to issued, and regenerates the file with the confirmed number.
- Void an issued invoice `tt invoice void <invoice id>` — sets status to void, which releases its entries to be billed again while the invoice keeps its number so the client's sequence stays gapless.
- Delete a draft `tt invoice delete <invoice id>` — only permitted while status is draft, since drafts hold no number and bill nothing.

### Edge Cases

| Case | Issue | How to Handle |
| --- | --- | --- |
| Client/project doesn't exist | The selection will be empty or not contain some from the given client/project | Allow it to be missing, don't flag or warn. |
| Start date is after end date | Filters out everything | Allow selection to be empty |
| Either date is after the present | Filters out some things | Allow selection to be empty |
| Filters on an invoice include entries already billed for | Risks double-billing time entries | Default to excluding them, add flag to manually include, such as in cases of invoice regeneration when billing did not actually occur. Regenerating an existing invoice looks up its entries through the invoice entries table rather than re-running the original filters, so a regenerated invoice always matches the one that was sent. |

## Client and Project Creation

Since there are likely multiple clients, and potentially multiple projects per client, we should be able to manage the clients and the projects. These primarily have names, though each client and potentially project can have a billable rate as well. Rate can be set to null, and it should default to inheriting from client, with the option to manually change per project.

Because commands accept a client by name or by alias in the same argument position, an alias has to be unique against client names as well as against other aliases. Otherwise an alias like `G8` could refer both to an abbreviation of G8 Capital and to a different client actually named G8, and the command would have no way to tell which was meant. The same rule applies to project aliases within a client. Creating an alias that collides should throw an error rather than resolve to a guess.

### Create new Client

Accepts client name as a string as the first argument without flags, adds optional flags.

Flags:
- Alias `--client-alias TFA`
- Billable rate `--pay-rate-hourly 35`

### Edit Client

Should always pass in client name/ID/alias as the first argument without flags.

Flags:
- client ID (alternative to name) `--id 123`
- New name `--new-client "G8 Capital"`
- New rate `--pay-rate-hourly 40`
- New alis `--alias G8`

### Create new project

Should always pass in client name/ID/alias as the first argument without flags, and second argument as project name without flags, adds optional flags.

Flags:
- Pay rate for the project `--pay-rate-hourly 45`

## Package and DB management

The package will be developed locally in this repository, though the working directory for the application should be something like ~/TimeTracker/ unless a user manually overrides that during setup. This will house the database and set environment variables that will be used for database access.
