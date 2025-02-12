CREATE TABLE IF NOT EXISTS account_metric (
    id SERIAL PRIMARY KEY,
    account_id VARCHAR(255) NOT NULL,
    metric_definition_id INTEGER NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,        -- 是否启用
    display_order INTEGER DEFAULT 0,        -- 显示顺序
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, metric_definition_id)
);

CREATE INDEX idx_account_metric_account_id ON account_metric(account_id);
CREATE INDEX idx_account_metric_definition_id ON account_metric(metric_definition_id);
