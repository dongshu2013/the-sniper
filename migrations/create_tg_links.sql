CREATE TABLE IF NOT EXISTS tg_link_status (
    id SERIAL PRIMARY KEY,
    tg_link TEXT NOT NULL,
    source TEXT,
    chat_id VARCHAR(255),
    chat_name VARCHAR(255),
    status VARCHAR(255) DEFAULT 'pending_pre_processing',
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tg_link)
);

CREATE INDEX idx_tg_link_status_tg_link ON tg_link_status(tg_link);

ALTER TABLE tg_link_status 
ADD COLUMN mark_name VARCHAR(255);

CREATE INDEX idx_tg_link_status_mark_name ON tg_link_status(mark_name);
