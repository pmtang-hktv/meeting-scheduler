-- Day-off / leave entries that team members mark in the owner's calendar.
-- start_date is inclusive; end_date is the inclusive LAST day off (so a single-day
-- off has start_date == end_date). The Google all-day event uses an exclusive end,
-- computed at write time.
CREATE TABLE IF NOT EXISTS day_offs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_chat_id INTEGER NOT NULL,
    person_name       TEXT NOT NULL,
    start_date        TEXT NOT NULL,   -- YYYY-MM-DD, inclusive
    end_date          TEXT NOT NULL,   -- YYYY-MM-DD, inclusive last day
    calendar_uid      TEXT,
    status            TEXT NOT NULL DEFAULT 'confirmed',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dayoffs_chat ON day_offs(requester_chat_id, status);
