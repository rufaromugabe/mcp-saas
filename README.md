# MCP SaaS Backend

A comprehensive **Model Context Protocol (MCP) Server as a Service** platform that allows users to deploy, manage, and interact with MCP servers through a simple REST API and real-time streaming interface.

## 🚀 Features

- **Multi-language Support**: Python, Node.js, Go, Rust, and more
- **Real-time Communication**: WebSocket-like SSE streaming for MCP events
- **MCP Configuration Support**: Direct deployment using MCP server configurations
- **Source Code Deployment**: Support for ZIP, TAR, Git repositories, and direct code
- **Resource Management**: Process isolation with monitoring and limits
- **Persistent Storage**: PostgreSQL for metadata, Redis for caching
- **Load Balancing**: Nginx reverse proxy with rate limiting
- **Health Monitoring**: Comprehensive health checks and metrics

## 🔧 MCP Server Configurations

The platform supports deploying MCP servers using standard MCP configuration format, eliminating the need for custom code packaging:

### Supported MCP Servers

**Memory Server**
```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-memory"]
}
```

**Filesystem Server**
```json
{
  "command": "npx", 
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/files"]
}
```

**GitHub Server**
```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "<YOUR_TOKEN>"
  }
}
```

**PostgreSQL Server**
```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-postgres"],
  "env": {
    "POSTGRES_CONNECTION_STRING": "postgresql://user:pass@host:5432/db"
  }
}
```

**Google Drive Server**
```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-gdrive"],
  "env": {
    "GOOGLE_CLIENT_ID": "<YOUR_CLIENT_ID>",
    "GOOGLE_CLIENT_SECRET": "<YOUR_CLIENT_SECRET>"
  }
}
```

### Custom MCP Servers

You can also deploy custom MCP servers by specifying the appropriate command and arguments:

```json
{
  "command": "python",
  "args": ["-m", "my_custom_mcp_server"],
  "env": {
    "API_KEY": "secret",
    "DEBUG": "true"
  },
  "cwd": "/path/to/server"
}
```

## 🏗️ Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │───▶│    Nginx    │───▶│   FastAPI   │
│ Application │    │   (Port 80) │    │ (Port 8000) │
└─────────────┘    └─────────────┘    └─────────────┘
                                             │
                   ┌─────────────────────────┼─────────────────────────┐
                   │                         │                         │
            ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
            │ PostgreSQL  │          │    Redis    │          │ MCP Servers │
            │ (Port 5432) │          │ (Port 6379) │          │  (stdio)    │
            └─────────────┘          └─────────────┘          └─────────────┘
```

## 📦 Installation & Setup

### Prerequisites

- Docker & Docker Compose
- Git (for repository cloning)
- 4GB RAM minimum
- 10GB disk space

### Quick Start

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd mcp-saas
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start the services**:
   ```bash
   docker-compose up -d
   ```

4. **Verify health**:
   ```bash
   curl http://localhost/health
   ```

### Manual Setup (Development)

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Start PostgreSQL and Redis**:
   ```bash
   docker-compose up -d postgres redis
   ```

3. **Run the application**:
   ```bash
   python app_enhanced.py
   ```

## 🔧 Configuration

### Environment Variables

Key configuration options (see `.env.example` for full list):

```bash
# Database
DATABASE_URL=postgresql://mcp_user:mcp_password@postgres:5432/mcp_saas

# Redis
REDIS_URL=redis://redis:6379

# Security
SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256

# Resource Limits
MAX_INSTANCES_PER_USER=10
MAX_MEMORY_MB=1024
MAX_CPU_PERCENT=80
```

### Nginx Configuration

The included `nginx.conf` provides:
- Rate limiting (10 req/s general, 1 req/min for deployments)
- Request size limits (100MB for uploads)
- Proper headers for SSE streaming
- Health check endpoints

## 📋 API Documentation

### Authentication

Currently supports simple token-based authentication. Send token in `Authorization: Bearer <token>` header.

### Core Endpoints

#### Deploy MCP Server

**Option 1: MCP Configuration (Recommended)**
```http
POST /api/v2/deploy
Content-Type: application/json

{
  "name": "memory-server",
  "source_type": "mcp_config",
  "mcp_config": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-memory"],
    "env": {
      "NODE_ENV": "production"
    }
  },
  "environment_vars": {
    "MEMORY_SIZE": "1GB"
  }
}
```

**Option 2: Traditional Code Upload**
```http
POST /api/v2/deploy
Content-Type: application/json

{
  "name": "my-mcp-server",
  "source_type": "git",
  "source_url": "https://github.com/user/mcp-server.git",
  "language": "python",
  "entry_point": "server.py",
  "dependencies": ["requests", "aiofiles"],
  "environment_vars": {
    "API_KEY": "secret"
  }
}
```

**Response:**
```json
{
  "instance_id": "uuid-here",
  "name": "my-mcp-server",
  "language": "python",
  "status": "running",
  "created_at": "2024-01-01T00:00:00Z",
  "sse_endpoint": "/mcp/uuid-here/stream",
  "api_endpoint": "/mcp/uuid-here/execute"
}
```

#### Execute MCP Command
```http
POST /mcp/{instance_id}/execute
Content-Type: application/json

{
  "method": "tools/list",
  "params": {}
}
```

#### Stream Events (SSE)
```http
GET /mcp/{instance_id}/stream
Accept: text/event-stream
```

**Events:**
```
data: {"type": "connected", "instance_id": "uuid"}

data: {"type": "notification", "method": "progress/update", "params": {...}}

data: {"type": "heartbeat", "timestamp": "2024-01-01T00:00:00Z"}
```

#### List Instances
```http
GET /instances
```

#### Stop Instance
```http
DELETE /mcp/{instance_id}
```

### System Endpoints

#### Health Check
```http
GET /health
```

#### System Statistics
```http
GET /stats
```

## 🎯 Usage Examples

### MCP Server Configurations (Recommended)

#### Memory Server
Store and retrieve information across conversations:
```bash
curl -X POST http://localhost/api/v2/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "name": "memory-server",
    "source_type": "mcp_config",
    "mcp_config": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    }
  }'
```

#### Filesystem Server
Access and manipulate files within allowed directories:
```bash
curl -X POST http://localhost/api/v2/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "name": "filesystem-server",
    "source_type": "mcp_config",
    "mcp_config": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/allowed"],
      "cwd": "/tmp"
    }
  }'
```

#### GitHub Server
Interact with GitHub repositories and issues:
```bash
curl -X POST http://localhost/api/v2/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "name": "github-server",
    "source_type": "mcp_config",
    "mcp_config": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_your_token_here"
      }
    },
    "environment_vars": {
      "GITHUB_OWNER": "your-username"
    }
  }'
```

#### PostgreSQL Server
Query and manage PostgreSQL databases:
```bash
curl -X POST http://localhost/api/v2/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "name": "postgres-server",
    "source_type": "mcp_config",
    "mcp_config": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "env": {
        "POSTGRES_CONNECTION_STRING": "postgresql://user:pass@localhost/dbname"
      }
    }
  }'
```

### Custom MCP Servers

#### Python MCP Server

1. **Prepare your MCP server code**:
   ```python
   # server.py
   import asyncio
   import json
   from typing import Dict, Any

   async def handle_request(request: Dict[str, Any]) -> Dict[str, Any]:
       method = request.get("method")
       params = request.get("params", {})
       
       if method == "tools/list":
           return {
               "result": {
                   "tools": [
                       {"name": "calculator", "description": "Basic calculator"}
                   ]
               }
           }
       
       return {"error": {"code": -32601, "message": "Method not found"}}

   async def main():
       while True:
           try:
               line = input()
               request = json.loads(line)
               response = await handle_request(request)
               print(json.dumps(response))
           except EOFError:
               break
           except Exception as e:
               error_response = {
                   "error": {"code": -32603, "message": str(e)}
               }
               print(json.dumps(error_response))

   if __name__ == "__main__":
       asyncio.run(main())
   ```

2. **Deploy via API**:
   ```bash
   curl -X POST http://localhost/deploy \
     -H "Content-Type: application/json" \
     -d '{
       "name": "calculator-server",
       "source_type": "direct",
       "source_data": "base64-encoded-server.py",
       "language": "python",
       "entry_point": "server.py",
       "dependencies": []
     }'
   ```

### Node.js MCP Server

1. **Create package.json**:
   ```json
   {
     "name": "mcp-node-server",
     "version": "1.0.0",
     "main": "server.js",
     "dependencies": {}
   }
   ```

2. **Create server.js**:
   ```javascript
   const readline = require('readline');

   const rl = readline.createInterface({
     input: process.stdin,
     output: process.stdout
   });

   rl.on('line', (line) => {
     try {
       const request = JSON.parse(line);
       const response = handleRequest(request);
       console.log(JSON.stringify(response));
     } catch (error) {
       console.log(JSON.stringify({
         error: { code: -32603, message: error.message }
       }));
     }
   });

   function handleRequest(request) {
     const { method, params } = request;
     
     if (method === 'tools/list') {
       return {
         result: {
           tools: [
             { name: 'timestamp', description: 'Get current timestamp' }
           ]
         }
       };
     }
     
     return { error: { code: -32601, message: 'Method not found' } };
   }
   ```

## 🔍 Monitoring & Debugging

### Logs

- **Application logs**: Available in `/app/logs/` directory
- **Instance logs**: Stored in database and accessible via API
- **Nginx logs**: Standard Docker logging

### Health Monitoring

The `/health` endpoint provides detailed status:
```json
{
  "status": "healthy",
  "services": {
    "redis": "connected",
    "mcp_manager": "healthy"
  },
  "active_instances": 5
}
```

### Database Queries

Connect to PostgreSQL to query instance data:
```sql
-- List all instances
SELECT name, language, status, created_at FROM mcp_instances;

-- Get instance logs
SELECT log_level, message, timestamp 
FROM mcp_instance_logs 
WHERE instance_id = 'your-uuid'
ORDER BY timestamp DESC;

-- Instance metrics
SELECT cpu_usage, memory_usage, timestamp 
FROM mcp_instance_metrics 
WHERE instance_id = 'your-uuid'
ORDER BY timestamp DESC LIMIT 10;
```

## 🔒 Security Considerations

### Production Deployment

1. **Change default passwords** in docker-compose.yml
2. **Set strong SECRET_KEY** in environment
3. **Enable HTTPS** by configuring SSL certificates
4. **Restrict CORS origins** in production
5. **Implement proper JWT authentication**
6. **Set up firewall rules**

### Resource Limits

Configure limits in `.env`:
```bash
MAX_INSTANCES_PER_USER=10
MAX_MEMORY_MB=1024
MAX_CPU_PERCENT=80
MAX_DISK_USAGE_MB=2048
```

## 🐛 Troubleshooting

### Common Issues

1. **Container fails to start**:
   - Check logs: `docker-compose logs mcp-saas-backend`
   - Verify environment variables
   - Ensure ports are available

2. **Database connection errors**:
   - Verify PostgreSQL is running: `docker-compose ps postgres`
   - Check connection string in `.env`
   - Ensure database exists

3. **MCP instance fails to deploy**:
   - Check source code format
   - Verify entry point exists
   - Review dependencies

4. **SSE stream not working**:
   - Check nginx configuration
   - Verify Content-Type headers
   - Test with curl: `curl -N http://localhost/mcp/id/stream`

### Debug Mode

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
python app_enhanced.py
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature-name`
3. Make changes and test
4. Submit pull request

## 📄 License

[Add your license here]

## 🆘 Support

- **Issues**: Create GitHub issues for bugs/features
- **Documentation**: Check the `/docs` directory
- **Community**: [Add community links]

---

**Note**: This is a production-ready foundation but may require additional customization for specific use cases. Always review security settings before deploying to production.
