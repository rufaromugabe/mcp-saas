"""
FastMCP-inspired transport layer for MCP SaaS platform.
Combines stdio expertise with HTTP transport patterns.
"""

import abc
import asyncio
import contextlib
import datetime
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

import anyio
import redis.asyncio as redis
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.sse import sse_client
from pydantic import BaseModel
from typing_extensions import Unpack

from mcp_stdio import MCPStdioWrapper

logger = logging.getLogger(__name__)


class SessionKwargs(TypedDict, total=False):
    """Keyword arguments for the MCP ClientSession constructor."""
    sampling_callback: Any
    list_roots_callback: Any
    logging_callback: Any
    message_handler: Any
    read_timeout_seconds: datetime.timedelta | None


class TransportConfig(BaseModel):
    """Configuration for transport types."""
    transport_type: Literal["stdio", "http", "sse"]
    suitable_for: List[str]
    default_timeout: int = 30
    supports_streaming: bool = True


class ClientTransport(abc.ABC):
    """Abstract base class for MCP client transport mechanisms."""

    @abc.abstractmethod
    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        """
        Establishes a connection and yields an active ClientSession.
        
        Args:
            **session_kwargs: Keyword arguments for ClientSession
            
        Yields:
            A mcp.ClientSession instance
        """
        raise NotImplementedError
        yield  # type: ignore

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


class MCPStdioTransport(ClientTransport):
    """Enhanced stdio transport using FastMCP patterns with our stdio wrapper."""
    
    def __init__(
        self,
        instance_id: str,
        command: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        stdio_wrapper: MCPStdioWrapper = None
    ):
        self.instance_id = instance_id
        self.command = command
        self.args = args or []
        self.cwd = cwd
        self.env = env or {}
        self.stdio_wrapper = stdio_wrapper
        
    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        """Connect using stdio with enhanced lifecycle management."""
        
        if self.stdio_wrapper:
            # Use our enhanced stdio wrapper
            try:
                await self.stdio_wrapper.start()
                # Create session from our wrapper's streams
                read_stream = self.stdio_wrapper.stdout_reader
                write_stream = self.stdio_wrapper.stdin_writer
                
                async with ClientSession(
                    read_stream, write_stream, **session_kwargs
                ) as session:
                    yield session
            finally:
                if self.stdio_wrapper:
                    await self.stdio_wrapper.stop()
        else:
            # Fallback to standard stdio client
            server_params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=self.env,
                cwd=self.cwd
            )
            async with stdio_client(server_params) as transport:
                read_stream, write_stream = transport
                async with ClientSession(
                    read_stream, write_stream, **session_kwargs
                ) as session:
                    yield session

    def __repr__(self) -> str:
        return f"<MCPStdio(instance_id='{self.instance_id}', command='{self.command}')>"


class MCPHttpTransport(ClientTransport):
    """HTTP transport for web-based MCP servers."""
    
    def __init__(
        self,
        url: str,
        headers: Dict[str, str] = None,
        timeout: datetime.timedelta = None
    ):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout or datetime.timedelta(seconds=30)
        
    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        """Connect using streamable HTTP."""
        client_kwargs = {
            "headers": self.headers,
            "timeout": self.timeout
        }
        
        async with streamablehttp_client(self.url, **client_kwargs) as transport:
            read_stream, write_stream, _ = transport
            async with ClientSession(
                read_stream, write_stream, **session_kwargs
            ) as session:
                yield session
                
    def __repr__(self) -> str:
        return f"<MCPHttp(url='{self.url}')>"


class MCPSSETransport(ClientTransport):
    """SSE transport for real-time MCP communication."""
    
    def __init__(
        self,
        url: str,
        headers: Dict[str, str] = None,
        sse_read_timeout: datetime.timedelta = None
    ):
        self.url = url
        self.headers = headers or {}
        self.sse_read_timeout = sse_read_timeout or datetime.timedelta(seconds=60)
        
    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        """Connect using SSE."""
        client_kwargs = {
            "headers": self.headers,
            "sse_read_timeout": self.sse_read_timeout.total_seconds()
        }
        
        async with sse_client(self.url, **client_kwargs) as transport:
            read_stream, write_stream = transport
            async with ClientSession(
                read_stream, write_stream, **session_kwargs
            ) as session:
                yield session
                
    def __repr__(self) -> str:
        return f"<MCPSSE(url='{self.url}')>"


class MCPSaaSTransport(ClientTransport):
    """Hybrid transport supporting multiple communication methods."""
    
    def __init__(
        self,
        mode: Literal["stdio", "http", "sse"],
        instance_id: str = None,
        **kwargs
    ):
        self.mode = mode
        self.instance_id = instance_id or f"transport-{id(self)}"
        
        if mode == "stdio":
            self.transport = MCPStdioTransport(instance_id=self.instance_id, **kwargs)
        elif mode == "http":
            self.transport = MCPHttpTransport(**kwargs)
        elif mode == "sse":
            self.transport = MCPSSETransport(**kwargs)
        else:
            raise ValueError(f"Unsupported transport mode: {mode}")
            
    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Unpack[SessionKwargs]
    ) -> AsyncIterator[ClientSession]:
        """Unified session management regardless of transport."""
        logger.info(f"Connecting via {self.mode} transport for instance {self.instance_id}")
        
        async with self.transport.connect_session(**session_kwargs) as session:
            yield session
            
    def __repr__(self) -> str:
        return f"<MCPSaaS(mode='{self.mode}', instance_id='{self.instance_id}')>"


class MCPSaaSSessionManager:
    """Enhanced session manager with Redis backend and multi-transport support."""
    
    def __init__(
        self,
        redis_client: redis.Redis,
        transport: ClientTransport = None,
        session_timeout: int = 300,
        cleanup_interval: int = 60
    ):
        self.redis_client = redis_client
        self.transport = transport
        self.session_timeout = session_timeout
        self.cleanup_interval = cleanup_interval
        self.task_group: Optional[anyio.abc.TaskGroup] = None
        self.active_sessions: Dict[str, ClientSession] = {}
        self.cleanup_task = None
        
    @contextlib.asynccontextmanager
    async def run(self):
        """Start the session manager with proper lifecycle management."""
        async with anyio.create_task_group() as task_group:
            self.task_group = task_group
            
            # Start periodic cleanup
            self.cleanup_task = task_group.start_soon(self._periodic_cleanup)
            
            logger.info("MCP SaaS Session Manager started")
            try:
                yield self
            finally:
                # Cleanup all active sessions
                await self._cleanup_all_sessions()
                logger.info("MCP SaaS Session Manager stopped")
                
    async def create_session(
        self,
        instance_id: str,
        transport: ClientTransport = None,
        **session_kwargs
    ) -> str:
        """Create a new MCP session."""
        if not transport and not self.transport:
            raise ValueError("No transport provided")
            
        session_transport = transport or self.transport
        session_id = f"session-{instance_id}-{id(session_transport)}"
        
        try:
            async with session_transport.connect_session(**session_kwargs) as session:
                # Initialize the session
                await session.initialize()
                
                # Store session info in Redis
                session_data = {
                    "instance_id": instance_id,
                    "session_id": session_id,
                    "transport_type": session_transport.__class__.__name__,
                    "created_at": datetime.datetime.utcnow().isoformat(),
                    "last_activity": datetime.datetime.utcnow().isoformat()
                }
                
                await self.redis_client.hset(
                    f"mcp:session:{session_id}",
                    mapping=session_data
                )
                await self.redis_client.expire(
                    f"mcp:session:{session_id}",
                    self.session_timeout
                )
                
                # Store in active sessions
                self.active_sessions[session_id] = session
                
                logger.info(f"Created MCP session {session_id} for instance {instance_id}")
                return session_id
                
        except Exception as e:
            logger.error(f"Failed to create session for instance {instance_id}: {e}")
            raise
            
    async def get_session(self, session_id: str) -> Optional[ClientSession]:
        """Get an active session by ID."""
        session = self.active_sessions.get(session_id)
        if session:
            # Update last activity
            await self.redis_client.hset(
                f"mcp:session:{session_id}",
                "last_activity",
                datetime.datetime.utcnow().isoformat()
            )
        return session
        
    async def close_session(self, session_id: str):
        """Close and cleanup a session."""
        session = self.active_sessions.pop(session_id, None)
        if session:
            try:
                await session.close()
            except Exception as e:
                logger.warning(f"Error closing session {session_id}: {e}")
                
        # Remove from Redis
        await self.redis_client.delete(f"mcp:session:{session_id}")
        logger.info(f"Closed MCP session {session_id}")
        
    async def _periodic_cleanup(self):
        """Periodically cleanup expired sessions."""
        while True:
            try:
                await anyio.sleep(self.cleanup_interval)
                await self._cleanup_expired_sessions()
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")
                
    async def _cleanup_expired_sessions(self):
        """Remove expired sessions."""
        current_time = datetime.datetime.utcnow()
        expired_sessions = []
        
        for session_id in list(self.active_sessions.keys()):
            session_data = await self.redis_client.hgetall(f"mcp:session:{session_id}")
            if not session_data:
                expired_sessions.append(session_id)
                continue
                
            last_activity = datetime.datetime.fromisoformat(
                session_data.get("last_activity", current_time.isoformat())
            )
            
            if (current_time - last_activity).total_seconds() > self.session_timeout:
                expired_sessions.append(session_id)
                
        for session_id in expired_sessions:
            await self.close_session(session_id)
            
        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
            
    async def _cleanup_all_sessions(self):
        """Cleanup all active sessions on shutdown."""
        for session_id in list(self.active_sessions.keys()):
            await self.close_session(session_id)


# Transport configuration mapping
TRANSPORT_CONFIGS = {
    "stdio": TransportConfig(
        transport_type="stdio",
        suitable_for=["python", "node", "custom_executables", "local_development"],
        default_timeout=30,
        supports_streaming=True
    ),
    "http": TransportConfig(
        transport_type="http", 
        suitable_for=["web_services", "microservices", "remote_apis", "production"],
        default_timeout=60,
        supports_streaming=True
    ),
    "sse": TransportConfig(
        transport_type="sse",
        suitable_for=["real_time_dashboards", "monitoring", "live_updates"],
        default_timeout=120,
        supports_streaming=True
    )
}


def infer_transport_type(source_info: Dict[str, Any]) -> Literal["stdio", "http", "sse"]:
    """Infer the best transport type based on source information."""
    
    # Check for explicit transport preference
    if "transport" in source_info:
        return source_info["transport"]
        
    # Check source type
    source_type = source_info.get("type", "").lower()
    
    if source_type in ["python", "node", "executable"]:
        return "stdio"
    elif source_type in ["web", "api", "http"]:
        return "http"
    elif source_type in ["realtime", "monitoring", "dashboard"]:
        return "sse"
        
    # Check URL patterns
    source_url = source_info.get("url", "")
    if source_url:
        if source_url.startswith(("http://", "https://")):
            if "/sse" in source_url or "/events" in source_url:
                return "sse"
            return "http"
            
    # Default to stdio for maximum compatibility
    return "stdio"


def create_transport(
    mode: Literal["stdio", "http", "sse"],
    instance_id: str,
    **kwargs
) -> MCPSaaSTransport:
    """Factory function to create transport instances."""
    return MCPSaaSTransport(mode=mode, instance_id=instance_id, **kwargs)
