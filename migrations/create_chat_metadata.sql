CREATE TABLE chat_metadata (
    id SERIAL PRIMARY KEY,
    chat_id VARCHAR(255) UNIQUE NOT NULL,  -- 群组的唯一标识
    name VARCHAR(255) DEFAULT '',          -- 群组名称
    about TEXT DEFAULT '',                 -- 群组介绍
    photo VARCHAR(255) DEFAULT '',      -- 群组头像信息
    username VARCHAR(255) DEFAULT '',      -- 群组用户名
    participants_count INTEGER DEFAULT 0,   -- 参与者数量
    admins TEXT DEFAULT '',             -- 管理员列表
    type VARCHAR(255) DEFAULT 'group',     -- 群组类型
    evaluated_at BIGINT DEFAULT 0,         -- 最后评估时间
    is_enabled BOOLEAN DEFAULT FALSE,       -- 是否启用 when collections associated with the group are enabled
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chat_metadata_chat_id ON chat_metadata(chat_id);
CREATE INDEX idx_chat_metadata_username ON chat_metadata(username);
CREATE INDEX idx_chat_metadata_evaluated_at ON chat_metadata(evaluated_at);
CREATE INDEX idx_chat_metadata_type ON chat_metadata(type);
CREATE INDEX idx_chat_metadata_is_enabled ON chat_metadata(is_enabled);