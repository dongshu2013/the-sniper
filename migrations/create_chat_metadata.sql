CREATE TABLE IF NOT EXISTS chat_metadata (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) DEFAULT '',
    about TEXT DEFAULT '',
    username VARCHAR(255) DEFAULT '',
    participants_count INTEGER DEFAULT 0,
    entity JSONB DEFAULT NULL,
    quality_reports JSONB DEFAULT '[]',
    is_blocked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chat_metadata_chat_id ON chat_metadata(chat_id);
CREATE INDEX idx_chat_metadata_username ON chat_metadata(username);
CREATE INDEX idx_chat_metadata_is_blocked ON chat_metadata(is_blocked);
