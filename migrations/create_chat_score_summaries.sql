CREATE TABLE IF NOT EXISTS chat_score_summaries (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(255) NOT NULL,
    score INTEGER NOT NULL,
    summary TEXT NOT NULL,
    highlights TEXT NOT NULL,
    messages_count INTEGER NOT NULL,
    unique_users_count INTEGER NOT NULL,
    last_message_timestamp BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, last_message_timestamp)
);

-- Create index on chat_id and last_message_timestamp for faster unique constraint checks
CREATE INDEX IF NOT EXISTS idx_chat_score_summaries_chat_version ON chat_score_summaries(chat_id, last_message_timestamp);
