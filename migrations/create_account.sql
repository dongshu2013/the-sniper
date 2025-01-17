CREATE TABLE IF NOT EXISTS account (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    session_file TEXT NOT NULL,
    api_id VARCHAR(255) NOT NULL,
    api_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(255) NOT NULL,
    status VARCHAR(255) DEFAULT 'active',
    last_active_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_account_username ON account(username);
CREATE INDEX idx_account_status ON account(status);
CREATE INDEX idx_account_last_active_at ON account(last_active_at);
