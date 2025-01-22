CREATE TABLE IF NOT EXISTS ip_pool (
    id SERIAL PRIMARY KEY,
    ip VARCHAR(255) UNIQUE NOT NULL,
    port INT NOT NULL,
    username VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    type VARCHAR(255) NOT NULL DEFAULT 'datacenter',
    region VARCHAR(255) NOT NULL DEFAULT 'random',
    running_accounts INT NOT NULL DEFAULT 0,
    expired_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ip_pool_expired_at ON ip_pool (expired_at);
CREATE INDEX IF NOT EXISTS idx_ip_pool_type ON ip_pool (type);
CREATE INDEX IF NOT EXISTS idx_ip_pool_region ON ip_pool (region);
CREATE INDEX IF NOT EXISTS idx_ip_pool_running_accounts ON ip_pool (running_accounts);
