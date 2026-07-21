ALTER TABLE memory_entries ADD COLUMN prompt_version TEXT DEFAULT '0';

INSERT INTO schema_version (version) VALUES (3);
