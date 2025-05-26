"""
Enhanced FastAPI application using FastMCP v2 patterns.
Combines stdio expertise with modern HTTP transport and session management.
"""

import asyncio
import json
import logging
import os
import tempfile
import uuid
import subprocess
import io
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional, Any, List, Literal
import base64
import datetime

import anyio
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator, Field
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
import yaml
import zipfile
import tarfile
import shutil

# Import our enhanced components
from transport import (
    MCPSaaSSessionManager, MCPSaaSTransport, create_transport,
    infer_transport_type, TRANSPORT_CONFIGS
)
from mcp_stdio import MCPInstanceManager, MCPStdioWrapper
from database import DatabaseService, MCPInstance, User
from composite import MCPSaaSComposite

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global managers
session_manager: Optional[MCPSaaSSessionManager] = None
instance_manager: Optional[MCPInstanceManager] = None
redis_client: Optional[redis.Redis] = None
db_service: Optional[DatabaseService] = None
composite_server: Optional[MCPSaaSComposite] = None


class RequestContextMiddleware:
    """Middleware that stores each request in context (FastMCP pattern)."""
    
    def __init__(self, app):
        self.app = app
        
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Store request context for downstream use
            request = Request(scope)
            # Add request tracking
            request_id = str(uuid.uuid4())
            logger.info(f"Request {request_id}: {request.method} {request.url}")
            
        await self.app(scope, receive, send)


class RateLimitingMiddleware:
    """Simple rate limiting middleware."""
    
    def __init__(self, app, requests_per_minute: int = 60):
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.request_counts = {}
        
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            client_ip = scope.get("client", ["unknown"])[0]
            current_time = datetime.datetime.utcnow()
            minute_key = current_time.strftime("%Y-%m-%d-%H-%M")
            
            # Track requests per IP per minute
            key = f"{client_ip}:{minute_key}"
            count = self.request_counts.get(key, 0)
            
            if count >= self.requests_per_minute:
                response = JSONResponse(
                    status_code=429,
                    content={"error": "Rate limit exceeded"}
                )
                await response(scope, receive, send)
                return
                
            self.request_counts[key] = count + 1
            
            # Cleanup old entries
            if len(self.request_counts) > 10000:  # Prevent memory leak
                cutoff = (current_time - datetime.timedelta(minutes=5)).strftime("%Y-%m-%d-%H-%M")
                self.request_counts = {
                    k: v for k, v in self.request_counts.items() 
                    if k.split(":")[1] > cutoff
                }
                
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Enhanced application lifespan with FastMCP patterns."""
    global session_manager, instance_manager, redis_client, db_service
    
    # Startup
    logger.info("Starting MCP SaaS Backend with FastMCP patterns...")
    
    try:
        # Initialize Redis connection (with fallback for local dev)
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        try:
            redis_client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            await redis_client.ping()
            logger.info("✅ Redis connected successfully")
        except Exception as e:
            logger.warning(f"⚠️  Redis connection failed: {e}. Running without Redis.")
            redis_client = None
        
        # Initialize database service
        database_url = os.getenv("DATABASE_URL", "sqlite:///./mcp_saas.db")
        try:
            db_service = DatabaseService(database_url)
            await db_service.initialize()
            logger.info("✅ Database initialized successfully")
        except Exception as e:
            logger.warning(f"⚠️  Database initialization failed: {e}. Running without database.")
            db_service = None
        
        # Initialize MCP instance manager (stdio expertise) - optional for basic functionality
        try:
            if redis_client:
                instance_manager = MCPInstanceManager(redis_url)
                await instance_manager.initialize()
                logger.info("✅ Instance manager initialized successfully")
            else:
                logger.warning("⚠️  Skipping instance manager (Redis not available)")
                instance_manager = None
        except Exception as e:
            logger.warning(f"⚠️  Instance manager initialization failed: {e}")
            instance_manager = None
        
        # Initialize session manager (FastMCP patterns) - optional for basic functionality
        try:
            if redis_client:
                session_manager = MCPSaaSSessionManager(
                    redis_client=redis_client,
                    session_timeout=int(os.getenv("SESSION_TIMEOUT", "300")),
                    cleanup_interval=int(os.getenv("CLEANUP_INTERVAL", "60"))
                )
                logger.info("✅ Session manager initialized successfully")
            else:
                logger.warning("⚠️  Skipping session manager (Redis not available)")
                session_manager = None
        except Exception as e:
            logger.warning(f"⚠️  Session manager initialization failed: {e}")
            session_manager = None
        
        logger.info("🚀 MCP SaaS Backend started successfully (some features may be limited)")
        yield
        
    except Exception as e:
        logger.error(f"❌ Failed to start application: {e}")
        raise
        
    # Shutdown
    logger.info("Shutting down MCP SaaS Backend...")
    if redis_client:
        await redis_client.close()


def create_production_app() -> FastAPI:
    """Create production-ready FastAPI app with FastMCP middleware patterns."""
    
    # Define middleware stack (FastMCP inspired)
    middleware = [
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        Middleware(TrustedHostMiddleware, allowed_hosts=["*"]),
        Middleware(RateLimitingMiddleware, requests_per_minute=120),
        Middleware(RequestContextMiddleware),  # FastMCP pattern
    ]
    
    app = FastAPI(
        title="MCP SaaS Platform",
        description="Production-ready MCP deployment platform with FastMCP patterns",
        version="2.0.0",
        middleware=middleware,
        lifespan=lifespan,
        docs_url="/docs" if os.getenv("ENVIRONMENT") != "production" else None,
        redoc_url="/redoc" if os.getenv("ENVIRONMENT") != "production" else None,
    )
    
    return app


# Create the application
app = create_production_app()

# Security
security = HTTPBearer()


# Enhanced Pydantic models with FastMCP patterns
class TransportMode(BaseModel):
    """Transport configuration model."""
    type: Literal["stdio", "http", "sse"]
    config: Dict[str, Any] = Field(default_factory=dict)
    timeout: Optional[int] = 30
    headers: Optional[Dict[str, str]] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    """MCP server configuration model."""
    command: str = Field(..., description="Command to run the MCP server")
    args: List[str] = Field(default_factory=list, description="Arguments for the command")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    cwd: Optional[str] = Field(None, description="Working directory")

class EnhancedDeploymentRequest(BaseModel):
    """Enhanced deployment request with MCP server configuration."""
    name: str = Field(..., min_length=1, max_length=100)
    source_type: Literal["mcp_config", "git", "zip", "tar", "dockerfile", "python", "node"] = "mcp_config"
    
    # MCP Server Configuration (primary method)
    mcp_config: Optional[MCPServerConfig] = None
    
    # Legacy support for other source types
    source_data: Optional[str] = None  # Base64 encoded for zip/tar (deprecated)
    source_url: Optional[str] = None   # For git repos or HTTP sources
    
    # Additional configuration
    environment_vars: Dict[str, str] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list)
    transport: Optional[TransportMode] = None  # Auto-inferred if not provided
    resources: Dict[str, Any] = Field(default_factory=dict)
    
    @field_validator('mcp_config')
    @classmethod
    def validate_mcp_config(cls, v, info):
        source_type = info.data.get('source_type')
        if source_type == 'mcp_config' and not v:
            raise ValueError("mcp_config required when source_type is 'mcp_config'")
        return v
    
    @field_validator('source_data')
    @classmethod
    def validate_source_data(cls, v, info):
        source_type = info.data.get('source_type')
        if source_type in ['zip', 'tar'] and not v:
            raise ValueError(f"source_data required for {source_type}")
        return v
        
    @field_validator('source_url')
    @classmethod
    def validate_source_url(cls, v, info):
        source_type = info.data.get('source_type')
        if source_type in ['git', 'dockerfile'] and not v:
            raise ValueError(f"source_url required for {source_type}")
        return v


class SessionInfo(BaseModel):
    """Session information model."""
    session_id: str
    instance_id: str
    transport_type: str
    status: str
    created_at: datetime.datetime
    last_activity: datetime.datetime


class MCPResponse(BaseModel):
    """Standardized MCP response model."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    session_id: Optional[str] = None
    transport_info: Optional[Dict[str, Any]] = None


# Dependency injection
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[str]:
    """Simple authentication dependency (extend with proper OAuth2)."""
    # TODO: Implement proper JWT/OAuth2 validation
    if credentials.credentials == "demo-token":
        return "demo-user"
    raise HTTPException(status_code=401, detail="Invalid authentication")


async def get_session_manager() -> MCPSaaSSessionManager:
    """Get the global session manager."""
    if not session_manager:
        raise HTTPException(status_code=503, detail="Session manager not available")
    return session_manager


async def get_instance_manager() -> MCPInstanceManager:
    """Get the global instance manager."""
    if not instance_manager:
        raise HTTPException(status_code=503, detail="Instance manager not available")
    return instance_manager


# Enhanced API endpoints

# MCP Configuration Examples Endpoint
@app.get("/api/v2/mcp/examples", response_model=Dict[str, Any])
async def get_mcp_server_examples():
    """Get examples of MCP server configurations."""
    
    examples = {
        "memory_server": {
            "name": "Memory MCP Server",
            "source_type": "mcp_config",
            "mcp_config": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-memory"],
                "env": {},
                "cwd": None
            },
            "description": "In-memory storage server for temporary data"
        },
        "filesystem_server": {
            "name": "Filesystem MCP Server", 
            "source_type": "mcp_config",
            "mcp_config": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"],
                "env": {},
                "cwd": None
            },
            "description": "File system access server with restricted path"
        },
        "github_server": {
            "name": "GitHub MCP Server",
            "source_type": "mcp_config", 
            "mcp_config": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": "your_token_here"
                },
                "cwd": None
            },
            "description": "GitHub API integration server"
        }
    }
    
    return {
        "examples": examples,
        "usage_note": "Use these examples as templates for your MCP server deployments. Simply POST to /api/v2/deploy with one of these configurations.",
        "format_specification": {
            "source_type": "Must be 'mcp_config' for direct MCP server configuration",
            "mcp_config": {
                "command": "The base command to execute (e.g., 'npx', 'python', 'node')",
                "args": "Array of arguments to pass to the command",
                "env": "Environment variables as key-value pairs", 
                "cwd": "Working directory (optional)"
            }
        }
    }

@app.post("/api/v2/deploy", response_model=MCPResponse)
async def deploy_mcp_enhanced(
    request: EnhancedDeploymentRequest,
    background_tasks: BackgroundTasks,
    current_user: str = Depends(get_current_user),
    session_mgr: MCPSaaSSessionManager = Depends(get_session_manager),
    instance_mgr: MCPInstanceManager = Depends(get_instance_manager)
):
    """Enhanced MCP deployment with transport selection and FastMCP patterns."""
    
    try:
        instance_id = str(uuid.uuid4())
        logger.info(f"Starting enhanced deployment {instance_id} for user {current_user}")
        
        # Infer transport type if not provided
        if not request.transport:
            transport_type = infer_transport_type({
                "type": request.source_type,
                "url": request.source_url,
                "name": request.name
            })
            transport_config = TRANSPORT_CONFIGS[transport_type]
            request.transport = TransportMode(
                type=transport_type,
                config={},
                timeout=transport_config.default_timeout
            )
        
        # Store deployment request in database
        if db_service:
            mcp_instance = MCPInstance(
                id=instance_id,
                name=request.name,
                user_id=current_user,
                source_type=request.source_type,
                source_url=request.source_url,
                transport_type=request.transport.type,
                status="deploying",
                environment_vars=request.environment_vars,
                dependencies=request.dependencies
            )
            await db_service.create_instance(mcp_instance)
        
        # Start deployment in background
        background_tasks.add_task(
            _deploy_instance_enhanced,
            instance_id,
            request,
            session_mgr,
            instance_mgr
        )
        
        return MCPResponse(
            success=True,
            data={
                "instance_id": instance_id,
                "status": "deploying",
                "transport_type": request.transport.type,
                "estimated_time": "2-5 minutes"
            },
            transport_info={
                "type": request.transport.type,
                "suitable_for": TRANSPORT_CONFIGS[request.transport.type].suitable_for,
                "supports_streaming": TRANSPORT_CONFIGS[request.transport.type].supports_streaming
            }
        )
        
    except Exception as e:
        logger.error(f"Deployment failed: {e}")
        return MCPResponse(
            success=False,
            error=str(e)
        )


@app.get("/api/v2/sessions", response_model=List[SessionInfo])
async def list_sessions(
    current_user: str = Depends(get_current_user),
    session_mgr: MCPSaaSSessionManager = Depends(get_session_manager)
):
    """List active MCP sessions with enhanced info."""
    
    sessions = []
    for session_id, session in session_mgr.active_sessions.items():
        session_data = await redis_client.hgetall(f"mcp:session:{session_id}")
        if session_data and session_data.get("user_id") == current_user:
            sessions.append(SessionInfo(
                session_id=session_id,
                instance_id=session_data["instance_id"],
                transport_type=session_data["transport_type"],
                status="active",
                created_at=datetime.datetime.fromisoformat(session_data["created_at"]),
                last_activity=datetime.datetime.fromisoformat(session_data["last_activity"])
            ))
    
    return sessions


@app.post("/api/v2/sessions/{instance_id}", response_model=MCPResponse)
async def create_session(
    instance_id: str,
    transport_override: Optional[TransportMode] = None,
    current_user: str = Depends(get_current_user),
    session_mgr: MCPSaaSSessionManager = Depends(get_session_manager),
    instance_mgr: MCPInstanceManager = Depends(get_instance_manager)
):
    """Create a new MCP session with specified transport."""
    
    try:
        # Get instance info
        if db_service:
            instance = await db_service.get_instance(instance_id)
            if not instance or instance.user_id != current_user:
                raise HTTPException(status_code=404, detail="Instance not found")
        
        # Determine transport
        if transport_override:
            transport_type = transport_override.type
            transport_config = transport_override.config
        else:
            # Use instance's default transport
            instance_data = await instance_mgr.get_instance_info(instance_id)
            if not instance_data:
                raise HTTPException(status_code=404, detail="Instance not running")
            transport_type = instance_data.get("transport_type", "stdio")
            transport_config = {}
        
        # Create transport
        if transport_type == "stdio":
            # Use our stdio wrapper
            stdio_wrapper = await instance_mgr.get_stdio_wrapper(instance_id)
            if not stdio_wrapper:
                raise HTTPException(status_code=404, detail="Stdio wrapper not found")
            
            transport = create_transport(
                mode="stdio",
                instance_id=instance_id,
                stdio_wrapper=stdio_wrapper,
                **transport_config
            )
        else:
            # Use HTTP/SSE transport
            base_url = os.getenv("MCP_BASE_URL", "http://localhost:8000")
            url = f"{base_url}/mcp/{instance_id}"
            
            transport = create_transport(
                mode=transport_type,
                instance_id=instance_id,
                url=url,
                **transport_config
            )
        
        # Create session
        session_id = await session_mgr.create_session(
            instance_id=instance_id,
            transport=transport
        )
        
        # Update session with user info
        await redis_client.hset(
            f"mcp:session:{session_id}",
            "user_id",
            current_user
        )
        
        return MCPResponse(
            success=True,
            data={
                "session_id": session_id,
                "instance_id": instance_id,
                "transport_type": transport_type
            },
            session_id=session_id,
            transport_info={
                "type": transport_type,
                "endpoint": url if transport_type != "stdio" else "stdio",
                "supports_streaming": TRANSPORT_CONFIGS[transport_type].supports_streaming
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        return MCPResponse(
            success=False,
            error=str(e)
        )


@app.get("/api/v2/sessions/{session_id}/stream")
async def stream_session_events(
    session_id: str,
    current_user: str = Depends(get_current_user),
    session_mgr: MCPSaaSSessionManager = Depends(get_session_manager)
):
    """Stream MCP session events using FastMCP patterns."""
    
    async def event_generator():
        """Generate SSE events from session."""
        session = await session_mgr.get_session(session_id)
        if not session:
            yield f"data: {json.dumps({'error': 'Session not found'})}\n\n"
            return
            
        # Verify user access
        session_data = await redis_client.hgetall(f"mcp:session:{session_id}")
        if session_data.get("user_id") != current_user:
            yield f"data: {json.dumps({'error': 'Access denied'})}\n\n"
            return
        
        # Stream events from Redis
        stream_key = f"mcp:events:{session_id}"
        last_id = "0"
        
        while True:
            try:
                # Read new messages
                messages = await redis_client.xread({stream_key: last_id}, block=1000, count=10)
                for stream, msgs in messages:
                    for msg_id, fields in msgs:
                        event_data = {
                            "id": msg_id.decode() if isinstance(msg_id, bytes) else msg_id,
                            "session_id": session_id,
                            "timestamp": fields.get("timestamp"),
                            "type": fields.get("type"),
                            "data": json.loads(fields.get("data", "{}"))
                        }
                        
                        yield f"data: {json.dumps(event_data)}\n\n"
                        last_id = msg_id
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error streaming events: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginx
        }
    )


async def _deploy_instance_enhanced(
    instance_id: str,
    request: EnhancedDeploymentRequest,
    session_mgr: MCPSaaSSessionManager,
    instance_mgr: MCPInstanceManager
):
    """Enhanced deployment function with MCP configuration support."""
    
    try:
        logger.info(f"Starting enhanced deployment for {instance_id}")
        
        # Update status
        if db_service:
            await db_service.update_instance_status(instance_id, "deploying")
        
        if request.source_type == "mcp_config":
            # Handle MCP server configuration directly
            if not request.mcp_config:
                raise ValueError("MCP configuration is required")
            
            logger.info(f"Deploying MCP server with configuration: {request.mcp_config.command}")
            
            # Merge environment variables
            env_vars = {**request.mcp_config.env, **request.environment_vars}
            
            # Create MCP instance directly from configuration
            await instance_mgr.create_instance(
                instance_id=instance_id,
                command=request.mcp_config.command,
                args=request.mcp_config.args,
                cwd=request.mcp_config.cwd,
                env=env_vars
            )
            
            logger.info(f"MCP server instance {instance_id} created successfully")
            
        else:
            # Legacy handling for file-based deployments
            work_dir = Path(tempfile.mkdtemp(prefix=f"mcp_{instance_id}_"))
            
            try:
                # Update status
                if db_service:
                    await db_service.update_instance_status(instance_id, "extracting")
                
                if request.source_type == "zip":
                    source_data = base64.b64decode(request.source_data)
                    with zipfile.ZipFile(io.BytesIO(source_data)) as zf:
                        zf.extractall(work_dir)
                elif request.source_type == "git":
                    # Clone git repo
                    subprocess.run([
                        "git", "clone", request.source_url, str(work_dir)
                    ], check=True)
                # ... other source types can be added here
                
                # Update status
                if db_service:
                    await db_service.update_instance_status(instance_id, "starting")
                
                # Create MCP instance using appropriate transport
                if request.transport and request.transport.type == "stdio":
                    # Use existing stdio deployment
                    await instance_mgr.create_instance(
                        instance_id=instance_id,
                        command=_build_command(work_dir, request),
                        cwd=str(work_dir),
                        env=request.environment_vars
                    )
                else:
                    # Deploy as HTTP service (extend this based on your needs)
                    logger.info(f"HTTP transport deployment not fully implemented for {instance_id}")
                
            finally:
                # Cleanup work directory
                import shutil
                shutil.rmtree(work_dir, ignore_errors=True)
        
        # Update final status
        if db_service:
            await db_service.update_instance_status(instance_id, "running")
            
        logger.info(f"Enhanced deployment completed for {instance_id}")
            
    except Exception as e:
        logger.error(f"Enhanced deployment failed for {instance_id}: {e}")
        if db_service:
            await db_service.update_instance_status(instance_id, "failed")
        raise


def _build_command(work_dir: Path, request: EnhancedDeploymentRequest) -> str:
    """Build command for stdio execution."""
    # Detect main file
    main_files = list(work_dir.glob("main.py")) + list(work_dir.glob("server.py")) + list(work_dir.glob("app.py"))
    
    if main_files:
        return f"python {main_files[0].name}"
    elif list(work_dir.glob("package.json")):
        return "npm start"
    else:
        raise ValueError("No main entry point found")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check with session manager status."""
    return {
        "status": "healthy",
        "session_manager": "active" if session_manager else "inactive",
        "instance_manager": "active" if instance_manager else "inactive",
        "redis": "connected" if redis_client else "disconnected",
        "database": "connected" if db_service else "disconnected",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "message": "MCP SaaS Backend is running in development mode"
    }


# Simple test endpoint
@app.get("/")
async def root():
    """Root endpoint with basic info."""
    return {
        "name": "MCP SaaS Platform",
        "version": "2.0.0",
        "description": "Production-ready MCP deployment platform with FastMCP patterns",
        "docs_url": "/docs",
        "health_url": "/health",
        "status": "running"
    }


# === Composite Server Endpoints ===

@app.post("/api/v2/composite/create", response_model=MCPResponse)
async def create_composite_server(
    name: str,
    description: str = "",
    current_user: str = Depends(get_current_user),
    session_mgr: MCPSaaSSessionManager = Depends(get_session_manager)
):
    """Create a new composite MCP server."""
    global composite_server
    
    try:
        composite_id = str(uuid.uuid4())
        
        # Initialize composite server if not exists
        if not composite_server:
            composite_server = MCPSaaSComposite(
                session_manager=session_mgr,
                redis_client=redis_client
            )
        
        # Create composite instance
        await composite_server.create_composite(
            composite_id=composite_id,
            name=name,
            description=description,
            user_id=current_user
        )
        
        return MCPResponse(
            success=True,
            data={
                "composite_id": composite_id,
                "name": name,
                "status": "created"
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to create composite server: {e}")
        return MCPResponse(success=False, error=str(e))


@app.post("/api/v2/composite/{composite_id}/mount", response_model=MCPResponse)
async def mount_instance_to_composite(
    composite_id: str,
    instance_id: str,
    prefix: str,
    current_user: str = Depends(get_current_user),
    session_mgr: MCPSaaSSessionManager = Depends(get_session_manager)
):
    """Mount an MCP instance to a composite server with a prefix."""
    
    try:
        if not composite_server:
            raise HTTPException(status_code=404, detail="No composite server available")
        
        # Verify ownership of both composite and instance
        if db_service:
            composite = await db_service.get_instance(composite_id)
            instance = await db_service.get_instance(instance_id)
            
            if not composite or composite.user_id != current_user:
                raise HTTPException(status_code=404, detail="Composite server not found")
            if not instance or instance.user_id != current_user:
                raise HTTPException(status_code=404, detail="Instance not found")
        
        # Create transport for the instance
        instance_data = await instance_manager.get_instance_info(instance_id)
        if not instance_data:
            raise HTTPException(status_code=404, detail="Instance not running")
        
        transport_type = instance_data.get("transport_type", "stdio")
        
        if transport_type == "stdio":
            stdio_wrapper = await instance_manager.get_stdio_wrapper(instance_id)
            if not stdio_wrapper:
                raise HTTPException(status_code=404, detail="Stdio wrapper not found")
            
            transport = create_transport(
                mode="stdio",
                instance_id=instance_id,
                stdio_wrapper=stdio_wrapper
            )
        else:
            base_url = os.getenv("MCP_BASE_URL", "http://localhost:8000")
            url = f"{base_url}/mcp/{instance_id}"
            transport = create_transport(
                mode=transport_type,
                instance_id=instance_id,
                url=url
            )
        
        # Mount the instance
        await composite_server.mount_instance(
            composite_id=composite_id,
            instance_id=instance_id,
            prefix=prefix,
            transport=transport
        )
        
        return MCPResponse(
            success=True,
            data={
                "composite_id": composite_id,
                "instance_id": instance_id,
                "prefix": prefix,
                "status": "mounted"
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to mount instance: {e}")
        return MCPResponse(success=False, error=str(e))


@app.get("/api/v2/composite/{composite_id}/tools", response_model=MCPResponse)
async def list_composite_tools(
    composite_id: str,
    current_user: str = Depends(get_current_user)
):
    """List all tools available in a composite server."""
    
    try:
        if not composite_server:
            raise HTTPException(status_code=404, detail="No composite server available")
        
        # Verify ownership
        if db_service:
            composite = await db_service.get_instance(composite_id)
            if not composite or composite.user_id != current_user:
                raise HTTPException(status_code=404, detail="Composite server not found")
        
        # Get tools from composite server
        tools = await composite_server.list_tools(composite_id)
        
        return MCPResponse(
            success=True,
            data={
                "composite_id": composite_id,
                "tools": [tool.dict() for tool in tools],
                "count": len(tools)
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to list composite tools: {e}")
        return MCPResponse(success=False, error=str(e))


@app.post("/api/v2/composite/{composite_id}/tools/{tool_name}/call", response_model=MCPResponse)
async def call_composite_tool(
    composite_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    current_user: str = Depends(get_current_user)
):
    """Call a tool in a composite server."""
    
    try:
        if not composite_server:
            raise HTTPException(status_code=404, detail="No composite server available")
        
        # Verify ownership
        if db_service:
            composite = await db_service.get_instance(composite_id)
            if not composite or composite.user_id != current_user:
                raise HTTPException(status_code=404, detail="Composite server not found")
        
        # Call tool through composite server
        result = await composite_server.call_tool(
            composite_id=composite_id,
            tool_name=tool_name,
            arguments=arguments
        )
        
        return MCPResponse(
            success=True,
            data={
                "tool_name": tool_name,
                "result": result,
                "composite_id": composite_id
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to call composite tool: {e}")
        return MCPResponse(success=False, error=str(e))


# === Enhanced Tool and Resource Endpoints ===

@app.post("/api/v2/sessions/{session_id}/tools/{tool_name}/call", response_model=MCPResponse)
async def call_tool_enhanced(
    session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    current_user: str = Depends(get_current_user),
    session_mgr: MCPSaaSSessionManager = Depends(get_session_manager)
):
    """Call a tool with enhanced error handling and logging."""
    
    try:
        # Verify session ownership
        session_data = await redis_client.hgetall(f"mcp:session:{session_id}")
        if not session_data or session_data.get("user_id") != current_user:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get session
        session = await session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not active")
        
        # Call tool with error masking
        try:
            result = await session.call_tool(tool_name, arguments)
            
            # Log successful tool call
            await redis_client.xadd(
                f"mcp:events:{session_id}",
                {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "success": "true",
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "data": json.dumps({"arguments": arguments, "result": result.dict()})
                }
            )
            
            return MCPResponse(
                success=True,
                data={
                    "tool_name": tool_name,
                    "result": result.dict(),
                    "session_id": session_id
                },
                session_id=session_id
            )
            
        except Exception as tool_error:
            # Log failed tool call
            await redis_client.xadd(
                f"mcp:events:{session_id}",
                {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "success": "false",
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "data": json.dumps({"arguments": arguments, "error": str(tool_error)})
                }
            )
            
            # Mask sensitive error details in production
            if os.getenv("ENVIRONMENT") == "production":
                error_msg = "Tool execution failed"
            else:
                error_msg = str(tool_error)
            
            return MCPResponse(
                success=False,
                error=error_msg,
                session_id=session_id
            )
        
    except Exception as e:
        logger.error(f"Failed to call tool: {e}")
        return MCPResponse(success=False, error=str(e))


# === Authentication Enhancement ===

class AuthSettings(BaseModel):
    """Authentication settings for FastMCP integration."""
    oauth2_provider: Optional[str] = None
    bearer_token_validation: bool = True
    jwt_secret: Optional[str] = None
    token_expiry_hours: int = 24


@app.post("/api/v2/auth/login", response_model=MCPResponse)
async def enhanced_login(
    username: str,
    password: str
):
    """Enhanced authentication endpoint (implement proper OAuth2/JWT)."""
    
    # TODO: Implement proper authentication
    # For demo purposes, accept demo credentials
    if username == "demo" and password == "demo":
        # Generate demo token (implement proper JWT)
        token = "demo-token"
        
        return MCPResponse(
            success=True,
            data={
                "access_token": token,
                "token_type": "bearer",
                "expires_in": 86400,  # 24 hours
                "user_id": "demo-user"
            }
        )
    
    return MCPResponse(
        success=False,
        error="Invalid credentials"
    )


# === Error Handling Enhancement ===

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Enhanced error handling with FastMCP patterns."""
    
    # Log error details
    logger.error(f"HTTP {exc.status_code}: {exc.detail} - {request.url}")
    
    # Mask sensitive errors in production
    if os.getenv("ENVIRONMENT") == "production" and exc.status_code >= 500:
        detail = "Internal server error"
    else:
        detail = exc.detail
    
    return JSONResponse(
        status_code=exc.status_code,
        content=MCPResponse(
            success=False,
            error=detail
        ).dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions with proper masking."""
    
    logger.error(f"Unexpected error: {exc} - {request.url}", exc_info=True)
    
    # Always mask unexpected errors in production
    if os.getenv("ENVIRONMENT") == "production":
        error_msg = "An unexpected error occurred"
    else:
        error_msg = str(exc)
    
    return JSONResponse(
        status_code=500,
        content=MCPResponse(
            success=False,
            error=error_msg
        ).dict()
    )
