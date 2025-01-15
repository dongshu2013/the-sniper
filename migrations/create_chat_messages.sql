CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    message_timestamp BIGINT NOT NULL,
    created_at BIGINT NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT,
    UNIQUE (chat_id, message_id)
);

-- Index for querying messages by chat_id
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id);

-- Index for timestamp-based queries within a chat
CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_timestamp ON chat_messages(chat_id, message_timestamp DESC);

-- Index for sender-based queries
CREATE INDEX IF NOT EXISTS idx_chat_messages_sender_id ON chat_messages(sender_id);
