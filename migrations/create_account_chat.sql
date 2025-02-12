CREATE TABLE IF NOT EXISTS account_chat (
    id SERIAL PRIMARY KEY,
    account_id VARCHAR(255) NOT NULL,
    chat_id VARCHAR(255) NOT NULL,
    status VARCHAR(255) DEFAULT 'watching',
    is_blocked BOOLEAN DEFAULT FALSE,      -- 是否被封禁
    is_private BOOLEAN DEFAULT FALSE,      -- 是否是私密群组
    is_enabled BOOLEAN DEFAULT FALSE,      -- 是否启用
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, chat_id)
);

CREATE INDEX idx_account_chat_account_id ON account_chat(account_id);
CREATE INDEX idx_account_chat_chat_id ON account_chat(chat_id);
CREATE INDEX idx_account_chat_status ON account_chat(status);
CREATE INDEX idx_account_chat_is_blocked ON account_chat(is_blocked);
CREATE INDEX idx_account_chat_is_private ON account_chat(is_private);
CREATE INDEX idx_account_chat_is_enabled ON account_chat(is_enabled);
