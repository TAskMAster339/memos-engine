CREATE INDEX IF NOT EXISTS idx_symbols_name_file ON symbols(name, file_id);

INSERT INTO schema_version (version) VALUES (5);
