CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL UNIQUE,
    state         TEXT NOT NULL DEFAULT 'IDLE',
    context_json  TEXT NOT NULL DEFAULT '{}',
    history_json  TEXT NOT NULL DEFAULT '[]',
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meetings (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    calendar_uid       TEXT UNIQUE,
    requester_chat_id  INTEGER NOT NULL,
    organizer_name     TEXT NOT NULL,
    purpose            TEXT NOT NULL,
    location_area      TEXT,
    location_exact     TEXT,
    location_confirmed INTEGER NOT NULL DEFAULT 0,
    is_external        INTEGER NOT NULL DEFAULT 0,
    travel_mins        INTEGER,
    start_dt           TEXT NOT NULL,
    end_dt             TEXT NOT NULL,
    duration_mins      INTEGER NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS owner_confirmations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id          INTEGER REFERENCES meetings(id),
    reason              TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    owner_message_id    INTEGER,
    requester_notified  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at         TEXT
);

CREATE TABLE IF NOT EXISTS follow_up_jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id     INTEGER NOT NULL REFERENCES meetings(id),
    trigger_dt     TEXT NOT NULL,
    job_type       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    apscheduler_id TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS travel_cache (
    destination_area TEXT PRIMARY KEY,
    travel_mins      INTEGER NOT NULL,
    cached_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_meetings_status      ON meetings(status);
CREATE INDEX IF NOT EXISTS idx_meetings_start_dt    ON meetings(start_dt);
CREATE INDEX IF NOT EXISTS idx_confirmations_status ON owner_confirmations(status);
CREATE INDEX IF NOT EXISTS idx_followups_trigger    ON follow_up_jobs(status, trigger_dt);
