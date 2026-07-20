CREATE VIRTUAL TABLE IF NOT EXISTS vec_symbols USING vec0(
    embedding FLOAT[384]
);

INSERT INTO schema_version (version) VALUES (2);
