-- sql/init.sql
-- Creates the stock_prices table with composite primary key for idempotent UPSERT.
-- Imported from: E2E_Implementation_Plan.md Section 2 (architecture).

CREATE TABLE IF NOT EXISTS stock_prices (
    symbol      VARCHAR(10)     NOT NULL,
    trade_date  DATE            NOT NULL,
    open_price  NUMERIC(12, 4),
    high_price  NUMERIC(12, 4),
    low_price   NUMERIC(12, 4),
    close_price NUMERIC(12, 4),
    volume      BIGINT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    PRIMARY KEY (symbol, trade_date)
);

-- Index on trade_date for cross-symbol date range queries (optional but useful).
CREATE INDEX IF NOT EXISTS idx_stock_prices_trade_date
    ON stock_prices (trade_date);
