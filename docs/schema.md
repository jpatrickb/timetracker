# Database Schema

## Time Entries

Serves to store the individual time entries for the user. The checks are simple pseudocode here, they're not intended to be copied directly into a SQL command or schema as is, obviously they'll need to be adapted.
Allows for a many to one relationship with Clients and with Projects.

Timestamps are stored as UTC Unix epoch seconds. We don't store any local time. Instead, the local calendar date is derived at read time from the timezone the machine reports when the command runs.

| Column Name | Data Type | PK | Unique | Check | Nullable | Constraint |
|---|---|---|---|---|---|---|
| ID | int | True | True |  | False | Column (unique) |
| Start Time | int (UTC epoch seconds) | |  | start_time <= current_time | False | Application code (requires checking current time) |
| End time | int (UTC epoch seconds) | | | start_time <= end_time | True | Table (requires checking other column on update) |
| Duration | int (seconds, generated column) | | | duration = end_time - start_time | True | Table (requires calculating/comparing against two values on update) |
| Client ID | int (FK → Clients.Client ID) | | | | True |  |
| Project ID | int (FK → Projects.Project ID) | | | | True | Same as client ID |
| Description | str | | | | True | None |
| Pay Rate Hourly | float | F | F |  | True | Column (checking float, and >=0) |
| Total Pay | float | F | F | pay rate * (duration / 3600), rounded to cents | True | Table (checking against pay rate and duration) |

The pay rate is copied onto the entry rather than read from the project at report time, so later rate changes never rewrite past work. It's taken from the project if the entry has one, otherwise from the client. The rate stored at clock-in is provisional and is looked up again at clock-out, so a rate set while the entry is open still applies. After that it only changes when the entry's client or project is edited, or when the user asks for it with `tt edit <id> --refresh-rate`.

An open entry (no end time) has no duration or total pay yet. It can't be linked to an invoice, and an entry that's on any invoice can't be reopened. Both rules are enforced by triggers.

When an entry has both a client and a project, a composite foreign key on (Project ID, Client ID) guarantees the project belongs to that client.

Entries carry no billing column. Billing status is derived, so an entry is billed when it is linked through the invoice entries to an invoice that has the status of `issued`.

## Clients

Serves to store the list of unique clients.

| Column Name | Data Type | PK | Unique | Check | Nullable | Constraint |
|---|---|---|---|---|---|---|
| Client ID | int | True | True |  | False | Column level uniqueness |
| Client Name | Str | False | True (case-insensitive) |  | False | Column level uniqueness |
| Pay rate hourly | float | False | False | >= 0 | True | Column |

## Projects

Serves to store the list of projects.

| Column Name | Data Type | PK | Unique | Check | Nullable | Constraint |
|---|---|---|---|---|---|---|
| Project ID | int | True | True |  | False | Column level uniqueness |
| Project Name | str | False | False (but client,project naming pair should be unique, case-insensitive) |  | False | Table, client_id and project name should be unique, referencing other columns |
| Client ID | int (FK → Clients.Client ID) |  |  |  | False |
| Pay rate hourly | float | False | False | >= 0 | True |

(Project ID, Client ID) is also declared unique so that project aliases and time entries can reference the pair with a composite foreign key.

A null pay rate means the project has no rate. When a client's rate changes, every project of that client whose rate still equals the client's old rate (including null) is updated to the new rate. Projects with their own rate are left alone.

## Client Alias

All client and project names and aliases compare case-insensitively (`COLLATE NOCASE`), so `tfa` finds `TFA` and the two count as a collision.

This table stores client aliases so that we can refer to a specific client using various different names. When a new client is created, the actual name of the client is inserted into this table as the first alias so that when we are searching for companies by names, we only need to check this table and don't need to check the client table as well.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| Client alias ID | int | T | T |  | F |
| Client Alias text | str | F | T |  | F |
| Client ID (FK) | int | F | F |  | F |

## Project Alias

This table stores project aliases so that we can refer to a specific project using various different names. When a new project is created, the actual name of the project is inserted into this table as the first alias so that when we are searching for projects by names, we only need to check this table and don't need to check the project table as well.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| Project alias ID | int | T | T |  | F |
| Project Alias text | str | F | Unique per client |  | F |
| Project ID (FK) | int | F | F |  | F |
| Client ID | int (composite FK with Project ID → Projects) | F | F | must match the project's client | F |

Project names are only unique within a client, so the alias table carries the client ID
to scope uniqueness. The composite foreign key on (Project ID, Client ID) guarantees the
copied client ID always matches the project's real client.

## Invoices

Serves to store the list of generated invoices, including unsent drafts. The invoice's contents aren't duplicated here. Instead, membership is recorded in the Invoice Entries table, so the projects, date span, and totals for any invoice are derived by querying the entries linked to it. Because each entry freezes its own pay rate and total pay at the billing time, that query reproduces the original invoice exactly, even after rates change. The client is the exception, and is stored on the invoice itself for the reason given below.

Invoice ID is an internal surrogate key used for linking, while Invoice Number is what appears on the document. A draft's Invoice Number column stays null until it is issued, so abandoning a draft costs nothing and the printed sequence stays gapless. The rendered draft file still shows a predicted number, computed at render time, so that drafts are ready to send. The prediction is not written to the database until issue.

The billing period is stored on the invoice rather than derived from its entries, because the invoice title shows the period that was requested (e.g. Sep 1 – Sep 14) even when the first or last days had no work. Storing it lets a regenerated invoice match the original exactly. Unlike timestamps, the period is a pair of calendar dates, so it's stored as `YYYY-MM-DD` text rather than UTC seconds.

Each client has its own invoice number sequence, so Patea and TechForce can both have an invoice #5. The client is stored on the invoice rather than derived from its entries, because the number sequence belongs to the client. The number is allocated at issue time as one greater than the highest number in use for that client, in the same transaction that sets the status to `issued`. A voided invoice keeps its number so that client's sequence never reuses or skips a value.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| Invoice ID | int | True | True |  | False |
| Invoice Number | int | False | Unique per client | null while draft, required once issued or void | True |
| Client ID | int (FK) | False | False |  | False |
| Date generated | int (UTC epoch seconds) | False | False | | False |
| Period start | str (YYYY-MM-DD, local date) | False | False | valid date, <= period end | False |
| Period end | str (YYYY-MM-DD, local date) | False | False | valid date | False |
| Status | str | False | False | one of draft, issued, void | False |

## Invoice Entries

This table links time entries to the invoices that they appear on. An entry may appear on any number of drafts, but on at most one issued invoice, which is what prevents double billing. This is enforced by a trigger rather than a unique index, because the status being constrained lives on the invoices table and SQLite prohibits subqueries in partial index where clauses.

Because the links are usually inserted while the invoice is still a draft and only become binding when it is issued, the guard that matters fires on the status transition rather than on insert. Issuing an invoice must abort if any of its entries already sit on another issued invoice.

A second rule applies here as well, which is that every entry linked to an invoice must belong to that invoice's client. Both the invoice and the entry name a client independently, so nothing in the table structure prevents them from disagreeing.

Two more rules round this out. Entries can only be linked while the invoice is still a draft, so an issued invoice's contents are fixed. And only finished entries can be linked, since an open entry has no pay to bill yet.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| Invoice ID | int (FK → Invoices.Invoice ID, cascade delete) | True (composite) |  |  | False |
| Entry ID | int (FK → Time Entries.ID, cascade delete) | True (composite) |  |  | False |

## User

Serves to store the user details. This table holds exactly one row, which is enforced by giving it a primary key that is checked to always equal 1. Invoices read the sender's name and address from it, so a second row would leave no way to tell which identity belongs on the document.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| User ID | int | True | True | id = 1 | False |
|First Name | Str | F |  |  | F |
| Last Name | Str | F |  |  | F |
| Street Address Line 1 | Str | F |  |  | F |
| Street Address Line 2 | Str | F |  |  | T |
| City | Str | F |  |  | F |
| State | Str | F |  |  | F |
| Zip Code | Str | F |  |  | F |

## Schema Versioning

The database stores its schema version in SQLite's built-in `user_version` pragma, which costs nothing and needs no table of its own. Migrations are an ordered list of steps, where step N moves the database from version N-1 to version N. On open, the application compares the file's version against the version it expects and applies any missing steps before running the command. Each step runs in its own transaction together with its version bump, so a failing migration leaves the database exactly as it was before that step. If the file's version is newer than any migration the app knows about, the app refuses to open it rather than guess.

This matters because the database accumulates real billable hours quickly, so a schema change made after the first invoice can't be handled by deleting the file and starting over. Version 1 is the schema described in this document.

Migrations are handled using numbered `.sql` files in the `src/timetracker/migrations/` directory, applied in filename order. Applied migrations can never be edited, and any changes to the schema should go in a new numbered file.

## Triggers

Rules that span tables are enforced with triggers, since SQLite `CHECK` constraints can only see their own row.

| Trigger | Fires on | Rule |
|---|---|---|
| `trg_invoice_issue_no_double_billing` | Invoice status changes to `issued` | None of its entries may already be on another issued invoice |
| `trg_invoice_entries_draft_only` | Linking an entry to an invoice | The invoice must be a draft |
| `trg_invoice_entries_same_client` | Linking an entry to an invoice | The entry's client must match the invoice's client |
| `trg_invoice_entries_closed_only` | Linking an entry to an invoice | The entry must have an end time |
| `trg_invoiced_entries_stay_closed` | Clearing an entry's end time | The entry must not be on any invoice |
