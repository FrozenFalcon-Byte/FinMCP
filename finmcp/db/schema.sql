-- FinMCP schema (SQLite). Idempotent: safe to run on every start.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS categories (
  id           INTEGER PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  kind         TEXT NOT NULL DEFAULT 'expense' CHECK (kind IN ('expense', 'income', 'transfer')),
  budget_limit REAL CHECK (budget_limit IS NULL OR budget_limit >= 0),   -- monthly limit, NULL = no budget
  description  TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS transactions (
  id                  INTEGER PRIMARY KEY,
  date                TEXT NOT NULL CHECK (length(date) = 10),           -- ISO date YYYY-MM-DD
  amount              REAL NOT NULL CHECK (amount >= 0),                   -- always positive; see direction
  direction           TEXT NOT NULL DEFAULT 'debit' CHECK (direction IN ('debit', 'credit')),
  currency            TEXT NOT NULL DEFAULT 'INR',
  merchant            TEXT NOT NULL,
  description         TEXT,
  category_id         INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  category_confidence REAL CHECK (category_confidence IS NULL OR (category_confidence >= 0 AND category_confidence <= 1)),
  category_source     TEXT CHECK (category_source IS NULL OR category_source IN ('user', 'memory', 'rule', 'llm', 'import', 'seed')),
  source              TEXT NOT NULL DEFAULT 'manual',                     -- manual | receipt | statement | sms | seed | api
  raw_text            TEXT,
  fingerprint         TEXT UNIQUE,                                        -- dedupe key for imports (NULL for manual entries)
  needs_review        INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant ON transactions(merchant);
CREATE INDEX IF NOT EXISTS idx_transactions_review ON transactions(needs_review) WHERE needs_review = 1;

CREATE TABLE IF NOT EXISTS merchant_memory (
  merchant_key TEXT PRIMARY KEY,
  category_id  INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  hits         INTEGER NOT NULL DEFAULT 1,
  last_seen    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
  id        INTEGER PRIMARY KEY,
  ts        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  actor     TEXT NOT NULL,
  action    TEXT NOT NULL,
  entity    TEXT,
  entity_id INTEGER,
  detail    TEXT
);

CREATE TABLE IF NOT EXISTS imports (
  id           INTEGER PRIMARY KEY,
  ts           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  source_kind  TEXT NOT NULL,        -- receipt | statement | csv | sms
  source_name  TEXT,
  parsed       INTEGER NOT NULL DEFAULT 0,
  inserted     INTEGER NOT NULL DEFAULT 0,
  duplicates   INTEGER NOT NULL DEFAULT 0,
  detail       TEXT
);

CREATE VIEW IF NOT EXISTS v_transactions AS
  SELECT t.id, t.date, t.amount, t.direction, t.currency, t.merchant, t.description,
         t.category_id, c.name AS category, c.kind AS category_kind,
         t.category_confidence, t.category_source, t.source, t.raw_text, t.fingerprint,
         t.needs_review, t.created_at, t.updated_at
  FROM transactions t LEFT JOIN categories c ON c.id = t.category_id;

CREATE VIEW IF NOT EXISTS monthly_summary AS
  SELECT substr(t.date, 1, 7) AS month,
         COALESCE(c.name, 'Uncategorized') AS category,
         COALESCE(c.kind, 'expense') AS category_kind,
         SUM(CASE WHEN t.direction = 'debit'  THEN t.amount ELSE 0 END) AS spent,
         SUM(CASE WHEN t.direction = 'credit' THEN t.amount ELSE 0 END) AS received,
         COUNT(*) AS n
  FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
  GROUP BY 1, 2, 3;

CREATE TRIGGER IF NOT EXISTS trg_transactions_updated
  AFTER UPDATE ON transactions FOR EACH ROW
  BEGIN
    UPDATE transactions SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = NEW.id;
  END;

INSERT OR IGNORE INTO schema_migrations (version) VALUES (1);
