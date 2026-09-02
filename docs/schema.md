# Database Schema

## Time Entries

Serves to store the individual time entries for the user. The checks are simple pseudocode here, they're not intended to be copied directly into a SQL command or schema as is, obviously they'll need to be adapted.
Allows for a many to one relationship with Clients and with Projects.

Timestamps are stored as UTC Unix epoch seconds. We don't store any local time. Instead, the local calendar date is derived at read time from the timezone the machine reports when the command runs.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| ID | int | True | True |  | False |
| Start Time | int (UTC epoch seconds) | |  | start_time <= current_time | False |
| End time | int (UTC epoch seconds) | | | start_time <= end_time | True |
| Duration | int (seconds, generated column) | | | duration = end_time - start_time | True |
| Client ID | int (FK → Clients.Client ID) | | | | True |
| Project ID | int (FK → Projects.Project ID) | | | | True |
| Description | str | | | | True |
| Pay Rate Hourly | float | F | F |  | True |
| Total Pay | float | F | F | pay rate * (duration / 3600), rounded to cents | True |
| invoice_id | int (FK) | | | | True |

Entries carry no billing column. Billing status is derived, so an entry is billed when it is linked through the invoice entries to an invoice that has the status of `issued`.

## Clients

Serves to store the list of unique clients.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| Client ID | int | True | True |  | False |
| Client Name | Str | False | True |  | False |
| Alias | str | False | True |  | True |
| Pay rate hourly | float | False | False |  | True |

## Projects

Serves to store the list of projects.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| Project ID | int | True | True |  | False |
| Project Name | str | False | False (but client,project naming pair should be unique) |  | False |
| Alias | str | False | True |  | True |
| Client ID | int (FK → Clients.Client ID) |  |  |  | False |
| Pay rate hourly | float | False | False |  | True |

## Invoices

Serves to store the list of generated invoices, including unsent drafts. The invoice's contents aren't duplicated here. Instead, membership is recorded in the Invoice Entries table, so the projects, date span, and totals for any invoice are derived by querying the entries linked to it. Because each entry freezes its own pay rate and total pay at the billing time, that query reproduces the original invoice exactly, even after rates change. The client is the exception, and is stored on the invoice itself for the reason given below.

Invoice ID is an internal surrogate key used for linking, while Invoice Number is what appears on the document. A draft's Invoice Number column stays null until it is issued, so abandoning a draft costs nothing and the printed sequence stays gapless. The rendered draft file still shows a predicted number, computed at render time, so that drafts are ready to send. The prediction is not written to the database until issue.

Each client has its own invoice number sequence, so Patea and TechForce can both have an invoice #5. The client is stored on the invoice rather than derived from its entries, because the number sequence belongs to the client. The number is allocated at issue time as one greater than the highest number in use for that client, in the same transaction that sets the status to `issued`. A voided invoice keeps its number so that client's sequence never reuses or skips a value.

| Column Name | Data Type | PK | Unique | Check | Nullable |
|---|---|---|---|---|---|
| Invoice ID | int | True | True |  | False |
| Invoice Number | int | False | Unique per client | null while draft, required once issued or void | True |
| Client ID | int (FK) | False | False |  | False |
| Date generated | int (UTC epoch seconds) | False | False | | False |
| Status | str | False | False | one of draft, issued, void | False |

## Invoice Entries

This table links time entries to the invoices that they appear on. An entry may appear on any number of drafts, but on at most one issued invoice, which is what prevents double billing. This is enforced by a trigger rather than a unique index, because the status being constrained lives on the invoices table and SQLite prohibits subqueries in partial index where clauses.

Because the links are usually inserted while the invoice is still a draft and only become binding when it is issued, the guard that matters fires on the status transition rather than on insert. Issuing an invoice must abort if any of its entries already sit on another issued invoice.

A second rule applies here as well, which is that every entry linked to an invoice must belong to that invoice's client. Both the invoice and the entry name a client independently, so nothing in the table structure prevents them from disagreeing.

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

The database stores its schema version in SQLite's built-in `user_version` pragma, which costs nothing and needs no table of its own. Migrations are an ordered list of steps, where step N moves the database from version N-1 to version N. On open, the application compares the file's version against the version it expects and applies any missing steps in a single transaction before running the command.

This matters because the database accumulates real billable hours quickly, so a schema change made after the first invoice can't be handled by deleting the file and starting over. Version 1 is the schema described in this document.

