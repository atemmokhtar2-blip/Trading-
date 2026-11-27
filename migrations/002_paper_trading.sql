-- Persistent paper-trading state. Idempotent; paper mode only.
CREATE TABLE IF NOT EXISTS paper_trade_log (
    fill_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity NUMERIC(36,18) NOT NULL CHECK (quantity > 0),
    price NUMERIC(36,18) NOT NULL CHECK (price > 0),
    fee NUMERIC(36,18) NOT NULL DEFAULT 0 CHECK (fee >= 0),
    reason TEXT NOT NULL,
    filled_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_trade_log_filled_at_idx ON paper_trade_log (filled_at DESC);

CREATE TABLE IF NOT EXISTS paper_brackets (
    symbol TEXT PRIMARY KEY,
    stop_price NUMERIC(36,18) NOT NULL CHECK (stop_price > 0),
    target_price NUMERIC(36,18),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_equity (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL,
    equity NUMERIC(36,18) NOT NULL,
    cash NUMERIC(36,18) NOT NULL,
    realized_pnl NUMERIC(36,18) NOT NULL,
    unrealized_pnl NUMERIC(36,18) NOT NULL,
    total_fees NUMERIC(36,18) NOT NULL
);
CREATE INDEX IF NOT EXISTS paper_equity_recorded_at_idx ON paper_equity (recorded_at DESC);
