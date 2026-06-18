CREATE TABLE public.stock_analyses (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(12) NOT NULL,
    exchange VARCHAR(20),
    market_cap NUMERIC(20, 2),
    current_price NUMERIC(12, 2) NOT NULL,
    intrinsic_value NUMERIC(12, 2),
    peg_ratio NUMERIC(8, 4),
    total_score VARCHAR(10) NOT NULL, -- Stores fractional scores like '5/12'
    conclusion VARCHAR(20) NOT NULL,  -- Stores outputs like 'BUY', 'HOLD', 'SELL'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Optimization: Index the ticker column for lightning-fast lookups
CREATE INDEX idx_stock_analyses_ticker ON stock_analyses(ticker);