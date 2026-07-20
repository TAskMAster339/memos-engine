CREATE TABLE schema_version (version INTEGER NOT NULL);

CREATE TABLE projects (
  id INTEGER PRIMARY KEY,
  root_path TEXT UNIQUE NOT NULL,
  name TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  path TEXT NOT NULL,
  language TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  mtime REAL,
  last_indexed_at TEXT,
  UNIQUE(project_id, path)
);

CREATE TABLE symbols (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  parent_symbol_id INTEGER REFERENCES symbols(id),
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  signature TEXT,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  exported INTEGER NOT NULL DEFAULT 0,
  content_hash TEXT NOT NULL
);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_file ON symbols(file_id);

CREATE TABLE call_edges (
  id INTEGER PRIMARY KEY,
  caller_symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
  callee_name TEXT NOT NULL,
  callee_symbol_id INTEGER REFERENCES symbols(id),
  line INTEGER NOT NULL
);
CREATE INDEX idx_calls_callee_name ON call_edges(callee_name);
CREATE INDEX idx_calls_callee_symbol ON call_edges(callee_symbol_id);

CREATE TABLE imports (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  imported_path TEXT NOT NULL,
  resolved_file_id INTEGER REFERENCES files(id)
);

CREATE TABLE memory_entries (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  scope_type TEXT NOT NULL,
  scope_id INTEGER,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  source_hash TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_memory_scope ON memory_entries(scope_type, scope_id);

INSERT INTO schema_version (version) VALUES (1);
