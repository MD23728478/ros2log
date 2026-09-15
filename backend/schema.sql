CREATE TABLE IF NOT EXISTS example_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_path TEXT NOT NULL UNIQUE,
    topics TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'finished', 'failed')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);
