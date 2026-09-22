CREATE TABLE IF NOT EXISTS time_entries (
  entry_id INTEGER PRIMARY KEY,
  start_time INTEGER NOT NULL,
  end_time INTEGER CHECK (end_time >= start_time),
  duration INTEGER GENERATED ALWAYS AS (end_time - start_time) STORED,
  client_id INTEGER REFERENCES clients(client_id),
  project_id INTEGER REFERENCES projects(project_id),
  description TEXT,
  pay_rate_hourly FLOAT CHECK (pay_rate_hourly >= 0.0),
  total_pay FLOAT GENERATED ALWAYS AS (ROUND(pay_rate_hourly * duration / 3600, 2)) STORED
);

CREATE TABLE IF NOT EXISTS clients (
  client_id INTEGER PRIMARY KEY,
  client_name TEXT NOT NULL UNIQUE,
  pay_rate_hourly FLOAT
);

CREATE TABLE IF NOT EXISTS projects (
  project_id INTEGER PRIMARY KEY,
  project_name TEXT NOT NULL,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  pay_rate_hourly FLOAT,
  CONSTRAINT unique_client_project_pair UNIQUE (client_id, project_name)
);

CREATE TABLE IF NOT EXISTS client_alias (
  client_alias_id INTEGER PRIMARY KEY,
  client_alias_text TEXT NOT NULL UNIQUE,
  client_id INTEGER NOT NULL REFERENCES clients(client_id)
);

CREATE TABLE IF NOT EXISTS project_alias (
  project_alias_id INTEGER PRIMARY KEY,
  project_alias_text TEXT NOT NULL UNIQUE,
  project_id INTEGER NOT NULL REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS invoices (
  invoice_id INTEGER PRIMARY KEY,
  invoice_number INTEGER,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  date_generated INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status in ('draft', 'issued', 'void')),
  CONSTRAINT unique_client_invoice UNIQUE (client_id, invoice_number)
);

CREATE TABLE IF NOT EXISTS invoice_entries (
  invoice_entry_id INTEGER UNIQUE NOT NULL,
  invoice_id INTEGER NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
  entry_id INTEGER NOT NULL REFERENCES time_entries(entry_id) ON DELETE CASCADE,
  PRIMARY KEY (invoice_id, entry_id)
);

CREATE TABLE IF NOT EXISTS user_info (
  user_id INTEGER PRIMARY KEY,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  address_line_1 TEXT NOT NULL,
  address_line_2 TEXT,
  city TEXT NOT NULL,
  state TEXT NOT NULL,
  zip_code INTEGER NOT NULL
);

-- Protect against entry added into issued invoice
CREATE TRIGGER IF NOT EXISTS trg_invoice_issue_no_double_billing
BEFORE UPDATE OF status ON invoices
FOR EACH ROW
WHEN NEW.status = 'issued' AND OLD.status <> 'issued'
BEGIN
  SELECT RAISE(ABORT, 'entry already billed on an issued invoice')
  WHERE EXISTS (
    SELECT mine. -- IN PROGRESS: RESUME HERE
  );
END;
