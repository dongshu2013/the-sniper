CREATE TABLE IF NOT EXISTS chat_metadata (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(255) UNIQUE NOT NULL,
    tme_link VARCHAR(255) NOT NULL, -- t.me link
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50),
    source_link VARCHAR(512),
    twitter VARCHAR(255),
    website VARCHAR(512),
    entity JSONB,  -- Stores {chain, address, ticker} as JSON
    about TEXT,
    participants_count INTEGER,
    processed_at BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for frequently queried fields
CREATE INDEX idx_chat_metadata_tme_link ON chat_metadata(tme_link);
CREATE INDEX idx_chat_metadata_chat_id ON chat_metadata(chat_id);
CREATE INDEX idx_chat_metadata_category ON chat_metadata(category);
CREATE INDEX idx_chat_metadata_processed_at ON chat_metadata(processed_at);
