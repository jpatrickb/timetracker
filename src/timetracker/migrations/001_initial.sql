CREATE TABLE IF NOT EXISTS time_entries (
  entry_id INTEGER PRIMARY KEY,
  start_time INTEGER NOT NULL,
  end_time INTEGER CHECK (end_time >= start_time),
  duration INTEGER GENERATED ALWAYS AS (end_time - start_time) STORED,
  client_id INTEGER REFERENCES clients(client_id),
  project_id INTEGER REFERENCES projects(project_id),
  description TEXT,
  pay_rate_hourly FLOAT CHECK (pay_rate_hourly >= 0.0),
  total_pay FLOAT GENERATED ALWAYS AS (ROUND(pay_rate_hourly * duration / 3600, 2)) STORED,
  -- When both are set, the project must belong to the client
  FOREIGN KEY (project_id, client_id) REFERENCES projects(project_id, client_id)
);

CREATE TABLE IF NOT EXISTS clients (
  client_id INTEGER PRIMARY KEY,
  client_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pay_rate_hourly FLOAT CHECK (pay_rate_hourly >= 0.0)
);

CREATE TABLE IF NOT EXISTS projects (
  project_id INTEGER PRIMARY KEY,
  project_name TEXT NOT NULL COLLATE NOCASE,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  pay_rate_hourly FLOAT CHECK (pay_rate_hourly >= 0.0),
  CONSTRAINT unique_client_project_pair UNIQUE (client_id, project_name),
  -- Lets project_alias reference the (project, client) pair below
  CONSTRAINT unique_project_client UNIQUE (project_id, client_id)
);

CREATE TABLE IF NOT EXISTS client_alias (
  client_alias_id INTEGER PRIMARY KEY,
  client_alias_text TEXT NOT NULL UNIQUE COLLATE NOCASE,
  client_id INTEGER NOT NULL REFERENCES clients(client_id)
);

CREATE TABLE IF NOT EXISTS project_alias (
  project_alias_id INTEGER PRIMARY KEY,
  project_alias_text TEXT NOT NULL COLLATE NOCASE,
  project_id INTEGER NOT NULL,
  -- Copied from the project so aliases can be unique per client
  client_id INTEGER NOT NULL,
  CONSTRAINT unique_client_project_alias UNIQUE (client_id, project_alias_text),
  -- Composite key guarantees client_id matches the project's actual client
  FOREIGN KEY (project_id, client_id) REFERENCES projects(project_id, client_id)
);

CREATE TABLE IF NOT EXISTS invoices (
  invoice_id INTEGER PRIMARY KEY,
  invoice_number INTEGER,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  date_generated INTEGER NOT NULL,
  -- Billing period as local calendar dates (YYYY-MM-DD), not UTC timestamps
  period_start TEXT NOT NULL CHECK (period_start = date(period_start)),
  period_end TEXT NOT NULL CHECK (period_end = date(period_end)),
  status TEXT NOT NULL CHECK (status in ('draft', 'issued', 'void')),
  CONSTRAINT period_in_order CHECK (period_start <= period_end),
  CONSTRAINT unique_client_invoice UNIQUE (client_id, invoice_number),
  -- Drafts have no number, issued and void invoices always do
  CONSTRAINT number_matches_status CHECK ((status = 'draft') = (invoice_number IS NULL))
);

CREATE TABLE IF NOT EXISTS invoice_entries (
  invoice_id INTEGER NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
  entry_id INTEGER NOT NULL REFERENCES time_entries(entry_id) ON DELETE CASCADE,
  PRIMARY KEY (invoice_id, entry_id)
);

CREATE TABLE IF NOT EXISTS user_info (
  user_id INTEGER PRIMARY KEY CHECK (user_id = 1),
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  address_line_1 TEXT NOT NULL,
  address_line_2 TEXT,
  city TEXT NOT NULL,
  state TEXT NOT NULL,
  zip_code TEXT NOT NULL
);

-- Issuing aborts if any of the invoice's entries already sit on another issued invoice
CREATE TRIGGER IF NOT EXISTS trg_invoice_issue_no_double_billing
BEFORE UPDATE OF status ON invoices
FOR EACH ROW
WHEN NEW.status = 'issued' AND OLD.status <> 'issued'
BEGIN
  SELECT RAISE(ABORT, 'entry already billed on an issued invoice')
  WHERE EXISTS (
    SELECT 1
    FROM invoice_entries AS mine
    JOIN invoice_entries AS other
      ON other.entry_id = mine.entry_id
      AND other.invoice_id <> mine.invoice_id
    JOIN invoices AS other_invoice
      ON other_invoice.invoice_id = other.invoice_id
    WHERE mine.invoice_id = NEW.invoice_id
      AND other_invoice.status = 'issued'
  );
END;

-- Entries can only be linked while the invoice is still a draft
CREATE TRIGGER IF NOT EXISTS trg_invoice_entries_draft_only
BEFORE INSERT ON invoice_entries
FOR EACH ROW
BEGIN
  SELECT RAISE(ABORT, 'entries can only be added to a draft invoice')
  WHERE (SELECT status FROM invoices WHERE invoice_id = NEW.invoice_id) <> 'draft';
END;

-- Every linked entry must belong to the invoice's client
CREATE TRIGGER IF NOT EXISTS trg_invoice_entries_same_client
BEFORE INSERT ON invoice_entries
FOR EACH ROW
BEGIN
  SELECT RAISE(ABORT, 'entry belongs to a different client than the invoice')
  WHERE (SELECT client_id FROM invoices WHERE invoice_id = NEW.invoice_id)
    IS NOT (SELECT client_id FROM time_entries WHERE entry_id = NEW.entry_id);
END;

-- Only finished entries can go on an invoice, since an open one has no pay yet
CREATE TRIGGER IF NOT EXISTS trg_invoice_entries_closed_only
BEFORE INSERT ON invoice_entries
FOR EACH ROW
BEGIN
  SELECT RAISE(ABORT, 'open entries cannot be added to an invoice')
  WHERE (SELECT end_time FROM time_entries WHERE entry_id = NEW.entry_id) IS NULL;
END;

-- ...and an entry on any invoice can't be reopened afterwards
CREATE TRIGGER IF NOT EXISTS trg_invoiced_entries_stay_closed
BEFORE UPDATE OF end_time ON time_entries
FOR EACH ROW
WHEN NEW.end_time IS NULL AND OLD.end_time IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'entries on an invoice cannot be reopened')
  WHERE EXISTS (SELECT 1 FROM invoice_entries WHERE entry_id = NEW.entry_id);
END;
