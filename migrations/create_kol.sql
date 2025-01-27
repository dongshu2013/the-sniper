CREATE TABLE IF NOT EXISTS kol (
    id SERIAL PRIMARY KEY,
    kol_id VARCHAR(255) NOT NULL,
    kol_name VARCHAR(255) NOT NULL,
    source VARCHAR(255) NOT NULL, -- chat_metadata.chat_id
    community_size INTEGER NOT NULL,
    engagement_size INTEGER NOT NULL,
    content_quality INTEGER NOT NULL,
    trading_influence INTEGER NOT NULL,
    advertisement_level INTEGER NOT NULL,
    investment_style INTEGER NOT NULL,
    content_quality_metadata JSONB DEFAULT NULL,
    trading_influence_metadata JSONB DEFAULT NULL,
    advertisement_level_metadata JSONB DEFAULT NULL,
    investment_style_metadata JSONB DEFAULT NULL,
    final_score INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_kol_kol_id ON kol(kol_id);
CREATE INDEX idx_kol_name ON kol(kol_name);
CREATE INDEX idx_kol_source ON kol(source);
CREATE INDEX idx_kol_community_size ON kol(community_size);
CREATE INDEX idx_kol_engagement_size ON kol(engagement_size);
CREATE INDEX idx_kol_final_score ON kol(final_score);
