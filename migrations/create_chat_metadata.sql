CREATE TABLE IF NOT EXISTS chat_metadata (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) DEFAULT '',
    entity_id INTEGER DEFAULT NULL,
    about TEXT DEFAULT '',
    username VARCHAR(255) DEFAULT '',
    participants_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for frequently queried fields
CREATE INDEX idx_chat_metadata_chat_id ON chat_metadata(chat_id);
CREATE INDEX idx_chat_metadata_entity_id ON chat_metadata(entity_id);
CREATE INDEX idx_chat_metadata_username ON chat_metadata(username);
