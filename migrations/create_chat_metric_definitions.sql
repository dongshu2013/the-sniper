CREATE TABLE chat_metric_definitions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,            -- metric 名称
    description TEXT DEFAULT '',           -- metric 描述
    prompt TEXT NOT NULL,                  -- 用于生成 metric 的提示词
    model VARCHAR(255) DEFAULT 'gpt-3.5-turbo', -- 使用的模型
    refresh_interval_hours INTEGER DEFAULT 24,   -- 刷新间隔，单位小时
    is_preset BOOLEAN DEFAULT FALSE,           -- 是否管理员预设
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chat_metric_definitions_name ON chat_metric_definitions(name);