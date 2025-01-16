CREATE TABLE IF NOT EXISTS tg_link_status (
    id SERIAL PRIMARY KEY,
    tg_link TEXT NOT NULL,
    chat_id VARCHAR(255),
    status VARCHAR(255) DEFAULT 'pending',
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tg_link)
);
