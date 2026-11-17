CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_control (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    trading_mode TEXT NOT NULL DEFAULT 'paper' CHECK (trading_mode = 'paper'),
    entries_paused BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO app_control (id, trading_mode, entries_paused)
VALUES (1, 'paper', TRUE) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    actor_telegram_id BIGINT,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_events_created_at_idx ON audit_events (created_at DESC);

CREATE TABLE IF NOT EXISTS worker_heartbeat (
    worker_name TEXT PRIMARY KEY,
    instance_id TEXT NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy_runs (
    id UUID PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'paper' CHECK (mode = 'paper'),
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS trade_intents (
    intent_id TEXT PRIMARY KEY,
    strategy_run_id UUID REFERENCES strategy_runs(id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity NUMERIC(36,18) NOT NULL CHECK (quantity > 0),
    status TEXT NOT NULL,
    decision_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES trade_intents(intent_id),
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity NUMERIC(36,18) NOT NULL CHECK (quantity > 0),
    price NUMERIC(36,18) NOT NULL CHECK (price > 0),
    fee NUMERIC(36,18) NOT NULL DEFAULT 0 CHECK (fee >= 0),
    filled_at TIMESTAMPTZ NOT NULL
);
