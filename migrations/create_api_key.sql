CREATE TABLE IF NOT EXISTS api_key (
    id SERIAL PRIMARY KEY,
    key JSONB NOT NULL,
    platform VARCHAR(255) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    status VARCHAR(255) DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (platform, account_id)
);
