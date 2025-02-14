CREATE TABLE IF NOT EXISTS user_metric (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    metric_definition_id INTEGER NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,        -- 是否启用
    display_order INTEGER DEFAULT 0,        -- 显示顺序
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, metric_definition_id)
);

CREATE INDEX idx_user_metric_user_id ON user_metric(user_id);
CREATE INDEX idx_user_metric_definition_id ON user_metric(metric_definition_id);
