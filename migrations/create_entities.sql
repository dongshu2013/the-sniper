CREATE TABLE entities (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(255) NOT NULL,
    reference VARCHAR(255) NOT NULL,
    metadata JSONB,
    website VARCHAR(255),
    twitter_username VARCHAR(255),
    logo VARCHAR(255),
    telegram VARCHAR(255),
    source_link VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (entity_type, reference)
);

CREATE INDEX idx_entities_entity_type ON entities(entity_type);
CREATE INDEX idx_entities_reference ON entities(reference);
