CREATE TABLE IF NOT EXISTS collections (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    is_public BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_collections_user_id ON collections(user_id);
CREATE INDEX idx_collections_is_public ON collections(is_public);

-- Junction table for many-to-many relationship between collections and groups
CREATE TABLE IF NOT EXISTS collection_group (
    id SERIAL PRIMARY KEY,
    collection_id INTEGER NOT NULL,
    chat_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
    FOREIGN KEY (chat_id) REFERENCES chat_metadata(chat_id) ON DELETE CASCADE,
    UNIQUE(collection_id, chat_id)
);

CREATE INDEX idx_collection_group_collection_id ON collection_group(collection_id);
CREATE INDEX idx_collection_group_chat_id ON collection_group(chat_id); 

create table if not exists collection_metric (
    id SERIAL PRIMARY KEY,
    collection_id INTEGER NOT NULL,
    metric_definition_id INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
    FOREIGN KEY (metric_definition_id) REFERENCES chat_metric_definitions(id) ON DELETE CASCADE,
    UNIQUE(collection_id, metric_definition_id)
);

CREATE INDEX idx_collection_metric_collection_id ON collection_metric(collection_id);
CREATE INDEX idx_collection_metric_metric_definition_id ON collection_metric(metric_definition_id);
