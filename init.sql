-- Initialize MCP SaaS database
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table for authentication
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- MCP instances table
CREATE TABLE IF NOT EXISTS mcp_instances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    language VARCHAR(50) NOT NULL,
    entry_point VARCHAR(500) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    source_url TEXT,
    command TEXT NOT NULL,
    working_directory TEXT,
    environment_vars JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'stopped',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_started_at TIMESTAMP WITH TIME ZONE,
    last_stopped_at TIMESTAMP WITH TIME ZONE
);

-- MCP instance logs table
CREATE TABLE IF NOT EXISTS mcp_instance_logs (    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    instance_id UUID REFERENCES mcp_instances(id) ON DELETE CASCADE,
    log_level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    log_metadata JSONB DEFAULT '{}'
);

-- MCP instance metrics table
CREATE TABLE IF NOT EXISTS mcp_instance_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    instance_id UUID REFERENCES mcp_instances(id) ON DELETE CASCADE,
    cpu_usage DECIMAL(5,2),
    memory_usage DECIMAL(10,2),
    requests_count INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    uptime_seconds INTEGER DEFAULT 0,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- API keys table for programmatic access
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Deployment history table
CREATE TABLE IF NOT EXISTS deployments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    instance_id UUID REFERENCES mcp_instances(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    deployment_config JSONB NOT NULL,
    status VARCHAR(50) NOT NULL,
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    build_logs TEXT
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_mcp_instances_user_id ON mcp_instances(user_id);
CREATE INDEX IF NOT EXISTS idx_mcp_instances_status ON mcp_instances(status);
CREATE INDEX IF NOT EXISTS idx_mcp_instance_logs_instance_id ON mcp_instance_logs(instance_id);
CREATE INDEX IF NOT EXISTS idx_mcp_instance_logs_timestamp ON mcp_instance_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_mcp_instance_metrics_instance_id ON mcp_instance_metrics(instance_id);
CREATE INDEX IF NOT EXISTS idx_mcp_instance_metrics_timestamp ON mcp_instance_metrics(timestamp);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_deployments_instance_id ON deployments(instance_id);
CREATE INDEX IF NOT EXISTS idx_deployments_user_id ON deployments(user_id);

-- Create a function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at columns
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_mcp_instances_updated_at BEFORE UPDATE ON mcp_instances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Insert a default admin user (password: admin123 - change in production!)
INSERT INTO users (email, password_hash, is_active, is_verified) 
VALUES ('admin@mcpsaas.local', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LwlAZ45.gYoFDpzm6', true, true)
ON CONFLICT (email) DO NOTHING;

-- Create a view for instance statistics
CREATE OR REPLACE VIEW instance_stats AS
SELECT 
    i.id,
    i.name,
    i.status,
    i.language,
    i.created_at,
    COALESCE(m.latest_cpu, 0) as latest_cpu_usage,
    COALESCE(m.latest_memory, 0) as latest_memory_usage,
    COALESCE(l.error_count, 0) as recent_errors,
    COALESCE(l.log_count, 0) as recent_logs
FROM mcp_instances i
LEFT JOIN (
    SELECT 
        instance_id,
        cpu_usage as latest_cpu,
        memory_usage as latest_memory,
        ROW_NUMBER() OVER (PARTITION BY instance_id ORDER BY timestamp DESC) as rn
    FROM mcp_instance_metrics
) m ON i.id = m.instance_id AND m.rn = 1
LEFT JOIN (
    SELECT 
        instance_id,
        COUNT(*) FILTER (WHERE log_level = 'ERROR') as error_count,
        COUNT(*) as log_count
    FROM mcp_instance_logs 
    WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '1 hour'
    GROUP BY instance_id
) l ON i.id = l.instance_id;
