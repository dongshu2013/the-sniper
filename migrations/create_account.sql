CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    tg_id VARCHAR(255) NOT NULL,
    username VARCHAR(255),
    api_id VARCHAR(255) NOT NULL,
    api_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(255) NOT NULL,
    status VARCHAR(255) DEFAULT 'active',
    fullname VARCHAR(255),
    last_active_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tg_id)
);

CREATE INDEX idx_accounts_username ON accounts(username);
CREATE INDEX idx_accounts_status ON accounts(status);
CREATE INDEX idx_accounts_last_active_at ON accounts(last_active_at);
