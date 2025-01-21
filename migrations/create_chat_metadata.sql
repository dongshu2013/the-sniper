CREATE TABLE IF NOT EXISTS chat_metadata (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(255) UNIQUE NOT NULL,
    chat_photo_url TEXT DEFAULT '', -- deprecated
    name VARCHAR(255) DEFAULT '',
    about TEXT DEFAULT '',
    photo JSONB DEFAULT NULL,
    username VARCHAR(255) DEFAULT '',
    participants_count INTEGER DEFAULT 0,
    pinned_messages JSONB DEFAULT '[]',
    initial_messages JSONB DEFAULT '[]',
    admins JSONB DEFAULT '[]',
    type VARCHAR(255) DEFAULT 'group',
    category VARCHAR(255),
    entity JSONB DEFAULT NULL,
    quality_reports JSONB DEFAULT '[]', -- deprecated
    quality_score DECIMAL(4,2) DEFAULT 0,
    ai_about TEXT DEFAULT '',
    is_blocked BOOLEAN DEFAULT FALSE,
    status VARCHAR(255) DEFAULT 'evaluating', -- deprecated
    evaluated_at BIGINT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chat_metadata_chat_id ON chat_metadata(chat_id);
CREATE INDEX idx_chat_metadata_username ON chat_metadata(username);
CREATE INDEX idx_chat_metadata_is_blocked ON chat_metadata(is_blocked);
CREATE INDEX idx_chat_metadata_quality_score ON chat_metadata(quality_score);
CREATE INDEX idx_chat_metadata_evaluated_at ON chat_metadata(evaluated_at);
CREATE INDEX idx_chat_metadata_type ON chat_metadata(type);
