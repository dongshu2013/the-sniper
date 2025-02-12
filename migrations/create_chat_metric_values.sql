CREATE TABLE chat_metric_values (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(255) NOT NULL,         -- 关联的群组ID
    metric_definition_id INTEGER NOT NULL,  -- 关联的 metric 定义
    is_enabled BOOLEAN DEFAULT TRUE,        -- 是否启用
    display_order INTEGER DEFAULT 0,        -- 显示顺序
    value TEXT,                            -- 计算结果
    confidence DECIMAL(4,2),               -- 置信度
    reason TEXT,                           -- 计算原因
    last_refresh_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,  -- 上次刷新时间
    next_refresh_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP + INTERVAL '24 hours', -- 下次刷新时间
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, metric_definition_id)  -- 确保每个群组的每个 metric 只有一个值
);

CREATE INDEX idx_chat_metric_values_chat_id ON chat_metric_values(chat_id);
CREATE INDEX idx_chat_metric_values_definition_id ON chat_metric_values(metric_definition_id);
CREATE INDEX idx_chat_metric_values_next_refresh ON chat_metric_values(next_refresh_at);
