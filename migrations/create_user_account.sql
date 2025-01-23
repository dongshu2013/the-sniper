CREATE TABLE IF NOT EXISTS user_account (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(255) DEFAULT 'active',
    UNIQUE(user_id, account_id)
);

CREATE INDEX idx_user_account_user_id ON user_account(user_id);
CREATE INDEX idx_user_account_account_id ON user_account(account_id);
