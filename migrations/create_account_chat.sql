CREATE TABLE IF NOT EXISTS account_chat (
    id SERIAL PRIMARY KEY,
    account_id VARCHAR(255) NOT NULL,
    chat_id VARCHAR(255) NOT NULL,
    status VARCHAR(255) DEFAULT 'watching',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, chat_id)
);

CREATE INDEX idx_account_chat_account_id ON account_chat(account_id);
CREATE INDEX idx_account_chat_chat_id ON account_chat(chat_id);
CREATE INDEX idx_account_chat_status ON account_chat(status);
