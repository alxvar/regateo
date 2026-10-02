-- regateo storage schema, version 1. Bump PRAGMA user_version in store.py when this changes.

CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,              -- match | gym | arena
    name        TEXT NOT NULL,
    config      TEXT NOT NULL,              -- JSON: the spec the run was started with
    status      TEXT NOT NULL,              -- running | done | failed | cancelled
    created_at  REAL NOT NULL,
    ended_at    REAL
);

CREATE TABLE IF NOT EXISTS matches (
    id            TEXT PRIMARY KEY,
    run_id        TEXT REFERENCES runs(id),
    scenario_id   TEXT NOT NULL,
    scenario      TEXT NOT NULL,            -- JSON Scenario
    seed          INTEGER,
    seller        TEXT NOT NULL,            -- JSON AgentRef
    buyer         TEXT NOT NULL,
    seller_key    TEXT NOT NULL,            -- AgentRef.key, for grouping head-to-heads
    buyer_key     TEXT NOT NULL,
    protocol      TEXT NOT NULL,
    status        TEXT NOT NULL,            -- running | done | failed
    outcome       TEXT,                     -- JSON Outcome
    deal          INTEGER,
    price         REAL,
    seller_share  REAL,
    buyer_share   REAL,
    end_reason    TEXT,
    cost_usd      REAL NOT NULL DEFAULT 0,
    meta          TEXT,                     -- JSON: pairing id, role swap, cell, ...
    started_at    REAL NOT NULL,
    ended_at      REAL
);
CREATE INDEX IF NOT EXISTS matches_run ON matches(run_id);
CREATE INDEX IF NOT EXISTS matches_agents ON matches(seller_key, buyer_key);

CREATE TABLE IF NOT EXISTS messages (
    match_id   TEXT NOT NULL REFERENCES matches(id),
    idx        INTEGER NOT NULL,
    sender     TEXT NOT NULL,
    text       TEXT NOT NULL,
    move       TEXT NOT NULL,               -- JSON Move, including agent meta
    t          REAL NOT NULL DEFAULT 0,
    latency_s  REAL NOT NULL DEFAULT 0,
    reading    TEXT,                        -- JSON Reading: the referee's reading of the message
    PRIMARY KEY (match_id, idx)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id            TEXT,
    profile             TEXT NOT NULL,
    provider            TEXT NOT NULL,
    model               TEXT NOT NULL,
    tags                TEXT NOT NULL,      -- JSON
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens   INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL NOT NULL DEFAULT 0,
    latency_s           REAL NOT NULL DEFAULT 0,
    cached              INTEGER NOT NULL DEFAULT 0,
    error               TEXT,
    created_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_calls_match ON llm_calls(match_id);

-- The model's thinking per call, kept apart so llm_calls stays small to scan. Added to existing databases
-- on open without a schema version bump, so processes on older code keep working.
CREATE TABLE IF NOT EXISTS llm_reasoning (
    call_id     INTEGER PRIMARY KEY REFERENCES llm_calls(id),
    text        TEXT NOT NULL
);

