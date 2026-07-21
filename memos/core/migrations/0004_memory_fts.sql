CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    project_id UNINDEXED
);

CREATE TRIGGER IF NOT EXISTS memory_fts_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO memory_fts(rowid, content, project_id)
    VALUES (new.id, new.content, new.project_id);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_ad AFTER DELETE ON memory_entries BEGIN
    DELETE FROM memory_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_au AFTER UPDATE ON memory_entries BEGIN
    DELETE FROM memory_fts WHERE rowid = old.id;
    INSERT INTO memory_fts(rowid, content, project_id)
    VALUES (new.id, new.content, new.project_id);
END;

INSERT INTO memory_fts(rowid, content, project_id)
SELECT id, content, project_id FROM memory_entries;

INSERT INTO schema_version (version) VALUES (4);
