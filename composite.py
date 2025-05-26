"""
Composite MCP server implementation supporting multiple MCP instances.
Based on FastMCP's mounting patterns for multi-server deployments.
"""

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Any, Literal
import datetime

import anyio
import redis.asyncio as redis
from mcp import ClientSession
from mcp.types import Tool, Resource, Prompt

from transport import MCPSaaSTransport, MCPSaaSSessionManager

logger = logging.getLogger(__name__)


class MountedInstance:
    """Represents a mounted MCP instance with prefix management."""
    
    def __init__(
        self,
        instance_id: str,
        prefix: str,
        transport: MCPSaaSTransport,
        session_manager: MCPSaaSSessionManager
    ):
        self.instance_id = instance_id
        self.prefix = prefix
        self.transport = transport
        self.session_manager = session_manager
        self._session: Optional[ClientSession] = None
        self._session_id: Optional[str] = None
        
    async def get_session(self) -> ClientSession:
        """Get or create a session for this mounted instance."""
        if not self._session:
            self._session_id = await self.session_manager.create_session(
                instance_id=self.instance_id,
                transport=self.transport
            )
            self._session = await self.session_manager.get_session(self._session_id)
            
        return self._session
        
    async def close(self):
        """Close the session for this mounted instance."""
        if self._session_id:
            await self.session_manager.close_session(self._session_id)
            self._session = None
            self._session_id = None
    
    def match_tool(self, tool_name: str) -> bool:
        """Check if a tool name matches this instance's prefix."""
        return tool_name.startswith(f"{self.prefix}_")
        
    def strip_tool_prefix(self, tool_name: str) -> str:
        """Remove the prefix from a tool name."""
        return tool_name.removeprefix(f"{self.prefix}_")
        
    def add_tool_prefix(self, tool_name: str) -> str:
        """Add the prefix to a tool name."""
        return f"{self.prefix}_{tool_name}"
        
    def match_resource(self, resource_uri: str) -> bool:
        """Check if a resource URI matches this instance's prefix."""
        return self._has_resource_prefix(resource_uri, self.prefix)
        
    def strip_resource_prefix(self, resource_uri: str) -> str:
        """Remove the prefix from a resource URI."""
        return self._remove_resource_prefix(resource_uri, self.prefix)
        
    def add_resource_prefix(self, resource_uri: str) -> str:
        """Add the prefix to a resource URI."""
        return self._add_resource_prefix(resource_uri, self.prefix)
        
    def match_prompt(self, prompt_name: str) -> bool:
        """Check if a prompt name matches this instance's prefix."""
        return prompt_name.startswith(f"{self.prefix}_")
        
    def strip_prompt_prefix(self, prompt_name: str) -> str:
        """Remove the prefix from a prompt name."""
        return prompt_name.removeprefix(f"{self.prefix}_")
        
    def add_prompt_prefix(self, prompt_name: str) -> str:
        """Add the prefix to a prompt name."""
        return f"{self.prefix}_{prompt_name}"
    
    @staticmethod
    def _add_resource_prefix(uri: str, prefix: str) -> str:
        """Add prefix to resource URI using protocol://prefix/path format."""
        if not prefix:
            return uri
            
        # Split URI into protocol and path
        uri_pattern = re.compile(r"^([^:]+://)(.*?)$")
        match = uri_pattern.match(uri)
        if not match:
            raise ValueError(f"Invalid URI format: {uri}")
            
        protocol, path = match.groups()
        return f"{protocol}{prefix}/{path}"
    
    @staticmethod  
    def _remove_resource_prefix(uri: str, prefix: str) -> str:
        """Remove prefix from resource URI."""
        if not prefix:
            return uri
            
        uri_pattern = re.compile(r"^([^:]+://)(.*?)$")
        match = uri_pattern.match(uri)
        if not match:
            return uri
            
        protocol, path = match.groups()
        prefix_pattern = f"^{re.escape(prefix)}/(.*?)$"
        path_match = re.match(prefix_pattern, path)
        
        if path_match:
            return f"{protocol}{path_match.group(1)}"
        return uri
    
    @staticmethod
    def _has_resource_prefix(uri: str, prefix: str) -> bool:
        """Check if URI has the specified prefix."""
        if not prefix:
            return False
            
        uri_pattern = re.compile(r"^([^:]+://)(.*?)$")
        match = uri_pattern.match(uri)
        if not match:
            return False
            
        _, path = match.groups()
        prefix_pattern = f"^{re.escape(prefix)}/"
        return bool(re.match(prefix_pattern, path))


class MCPSaaSComposite:
    """Composite MCP server supporting multiple mounted instances."""
    
    def __init__(
        self,
        redis_client: redis.Redis,
        session_manager: MCPSaaSSessionManager,
        name: str = "MCP-SaaS-Composite"
    ):
        self.name = name
        self.redis_client = redis_client
        self.session_manager = session_manager
        self.mounted_instances: Dict[str, MountedInstance] = {}
        self.task_group: Optional[anyio.abc.TaskGroup] = None
        
        # Cache for performance
        self._tools_cache: Optional[Dict[str, Any]] = None
        self._resources_cache: Optional[Dict[str, Any]] = None
        self._prompts_cache: Optional[Dict[str, Any]] = None
        self._cache_expiry: Optional[datetime.datetime] = None
        self._cache_duration = datetime.timedelta(minutes=5)
        
    @asynccontextmanager
    async def run(self):
        """Start the composite server with proper lifecycle management."""
        async with anyio.create_task_group() as task_group:
            self.task_group = task_group
            
            # Start cache refresh task
            task_group.start_soon(self._cache_refresh_loop)
            
            logger.info(f"Composite MCP server '{self.name}' started")
            try:
                yield self
            finally:
                # Cleanup all mounted instances
                await self._cleanup_all_instances()
                logger.info(f"Composite MCP server '{self.name}' stopped")
    
    async def mount(
        self,
        instance_id: str,
        prefix: str,
        transport: MCPSaaSTransport,
        verify_connection: bool = True
    ) -> bool:
        """Mount an MCP instance with the given prefix."""
        
        if prefix in self.mounted_instances:
            logger.warning(f"Instance with prefix '{prefix}' already mounted")
            return False
            
        try:
            mounted = MountedInstance(
                instance_id=instance_id,
                prefix=prefix,
                transport=transport,
                session_manager=self.session_manager
            )
            
            # Verify connection if requested
            if verify_connection:
                session = await mounted.get_session()
                # Test basic connection
                tools = await session.list_tools()
                logger.info(f"Mounted instance {instance_id} with {len(tools)} tools")
            
            self.mounted_instances[prefix] = mounted
            self._invalidate_cache()
            
            logger.info(f"Successfully mounted instance {instance_id} with prefix '{prefix}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to mount instance {instance_id}: {e}")
            return False
    
    async def unmount(self, prefix: str) -> bool:
        """Unmount an MCP instance."""
        mounted = self.mounted_instances.pop(prefix, None)
        if mounted:
            await mounted.close()
            self._invalidate_cache()
            logger.info(f"Unmounted instance with prefix '{prefix}'")
            return True
        return False
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools from all mounted instances with prefixes."""
        await self._ensure_cache_valid()
        
        if self._tools_cache is None:
            tools = []
            
            for prefix, mounted in self.mounted_instances.items():
                try:
                    session = await mounted.get_session()
                    instance_tools = await session.list_tools()
                    
                    for tool in instance_tools:
                        prefixed_tool = {
                            **tool.model_dump(),
                            "name": mounted.add_tool_prefix(tool.name),
                            "instance_id": mounted.instance_id,
                            "prefix": prefix
                        }
                        tools.append(prefixed_tool)
                        
                except Exception as e:
                    logger.error(f"Failed to list tools from {prefix}: {e}")
                    
            self._tools_cache = tools
            
        return self._tools_cache
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> List[Any]:
        """Call a tool, routing to the appropriate mounted instance."""
        
        # Find the mounted instance that owns this tool
        for mounted in self.mounted_instances.values():
            if mounted.match_tool(tool_name):
                try:
                    session = await mounted.get_session()
                    original_tool_name = mounted.strip_tool_prefix(tool_name)
                    
                    logger.info(f"Calling tool '{original_tool_name}' on instance {mounted.instance_id}")
                    result = await session.call_tool(original_tool_name, arguments)
                    
                    # Log result to Redis for monitoring
                    await self._log_tool_call(mounted.instance_id, tool_name, arguments, result)
                    
                    return result
                    
                except Exception as e:
                    logger.error(f"Failed to call tool {tool_name} on {mounted.instance_id}: {e}")
                    raise
        
        raise ValueError(f"Tool '{tool_name}' not found in any mounted instance")
    
    async def list_resources(self) -> List[Dict[str, Any]]:
        """List all resources from all mounted instances with prefixes."""
        await self._ensure_cache_valid()
        
        if self._resources_cache is None:
            resources = []
            
            for prefix, mounted in self.mounted_instances.items():
                try:
                    session = await mounted.get_session()
                    instance_resources = await session.list_resources()
                    
                    for resource in instance_resources:
                        prefixed_resource = {
                            **resource.model_dump(),
                            "uri": mounted.add_resource_prefix(resource.uri),
                            "instance_id": mounted.instance_id,
                            "prefix": prefix
                        }
                        resources.append(prefixed_resource)
                        
                except Exception as e:
                    logger.error(f"Failed to list resources from {prefix}: {e}")
                    
            self._resources_cache = resources
            
        return self._resources_cache
    
    async def read_resource(self, resource_uri: str) -> Any:
        """Read a resource, routing to the appropriate mounted instance."""
        
        # Find the mounted instance that owns this resource
        for mounted in self.mounted_instances.values():
            if mounted.match_resource(resource_uri):
                try:
                    session = await mounted.get_session()
                    original_uri = mounted.strip_resource_prefix(resource_uri)
                    
                    logger.info(f"Reading resource '{original_uri}' from instance {mounted.instance_id}")
                    result = await session.read_resource(original_uri)
                    
                    # Log access to Redis for monitoring
                    await self._log_resource_access(mounted.instance_id, resource_uri)
                    
                    return result
                    
                except Exception as e:
                    logger.error(f"Failed to read resource {resource_uri} from {mounted.instance_id}: {e}")
                    raise
        
        raise ValueError(f"Resource '{resource_uri}' not found in any mounted instance")
    
    async def list_prompts(self) -> List[Dict[str, Any]]:
        """List all prompts from all mounted instances with prefixes."""
        await self._ensure_cache_valid()
        
        if self._prompts_cache is None:
            prompts = []
            
            for prefix, mounted in self.mounted_instances.items():
                try:
                    session = await mounted.get_session()
                    instance_prompts = await session.list_prompts()
                    
                    for prompt in instance_prompts:
                        prefixed_prompt = {
                            **prompt.model_dump(),
                            "name": mounted.add_prompt_prefix(prompt.name),
                            "instance_id": mounted.instance_id,
                            "prefix": prefix
                        }
                        prompts.append(prefixed_prompt)
                        
                except Exception as e:
                    logger.error(f"Failed to list prompts from {prefix}: {e}")
                    
            self._prompts_cache = prompts
            
        return self._prompts_cache
    
    async def get_prompt(self, prompt_name: str, arguments: Dict[str, Any] = None) -> Any:
        """Get a prompt, routing to the appropriate mounted instance."""
        
        # Find the mounted instance that owns this prompt
        for mounted in self.mounted_instances.values():
            if mounted.match_prompt(prompt_name):
                try:
                    session = await mounted.get_session()
                    original_prompt_name = mounted.strip_prompt_prefix(prompt_name)
                    
                    logger.info(f"Getting prompt '{original_prompt_name}' from instance {mounted.instance_id}")
                    result = await session.get_prompt(original_prompt_name, arguments)
                    
                    # Log prompt usage to Redis for monitoring
                    await self._log_prompt_usage(mounted.instance_id, prompt_name, arguments)
                    
                    return result
                    
                except Exception as e:
                    logger.error(f"Failed to get prompt {prompt_name} from {mounted.instance_id}: {e}")
                    raise
        
        raise ValueError(f"Prompt '{prompt_name}' not found in any mounted instance")
    
    async def get_status(self) -> Dict[str, Any]:
        """Get status of all mounted instances."""
        status = {
            "name": self.name,
            "mounted_instances": len(self.mounted_instances),
            "instances": {}
        }
        
        for prefix, mounted in self.mounted_instances.items():
            try:
                # Test connection
                session = await mounted.get_session()
                tools = await session.list_tools()
                resources = await session.list_resources()
                prompts = await session.list_prompts()
                
                status["instances"][prefix] = {
                    "instance_id": mounted.instance_id,
                    "status": "healthy",
                    "tools_count": len(tools),
                    "resources_count": len(resources),
                    "prompts_count": len(prompts)
                }
            except Exception as e:
                status["instances"][prefix] = {
                    "instance_id": mounted.instance_id,
                    "status": "unhealthy",
                    "error": str(e)
                }
        
        return status
    
    async def _ensure_cache_valid(self):
        """Ensure cache is valid or refresh it."""
        now = datetime.datetime.utcnow()
        if self._cache_expiry is None or now > self._cache_expiry:
            self._invalidate_cache()
            self._cache_expiry = now + self._cache_duration
    
    def _invalidate_cache(self):
        """Invalidate all caches."""
        self._tools_cache = None
        self._resources_cache = None
        self._prompts_cache = None
        self._cache_expiry = None
    
    async def _cache_refresh_loop(self):
        """Periodically refresh cache."""
        while True:
            try:
                await anyio.sleep(self._cache_duration.total_seconds())
                self._invalidate_cache()
            except Exception as e:
                logger.error(f"Error in cache refresh loop: {e}")
    
    async def _log_tool_call(
        self,
        instance_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any
    ):
        """Log tool call for monitoring."""
        log_data = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "type": "tool_call",
            "instance_id": instance_id,
            "tool_name": tool_name,
            "arguments_size": len(json.dumps(arguments)),
            "success": True
        }
        
        await self.redis_client.xadd(
            f"mcp:logs:{instance_id}",
            log_data,
            maxlen=1000
        )
    
    async def _log_resource_access(self, instance_id: str, resource_uri: str):
        """Log resource access for monitoring."""
        log_data = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "type": "resource_access",
            "instance_id": instance_id,
            "resource_uri": resource_uri
        }
        
        await self.redis_client.xadd(
            f"mcp:logs:{instance_id}",
            log_data,
            maxlen=1000
        )
    
    async def _log_prompt_usage(
        self,
        instance_id: str,
        prompt_name: str,
        arguments: Dict[str, Any] = None
    ):
        """Log prompt usage for monitoring."""
        log_data = {
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "type": "prompt_usage",
            "instance_id": instance_id,
            "prompt_name": prompt_name,
            "has_arguments": arguments is not None
        }
        
        await self.redis_client.xadd(
            f"mcp:logs:{instance_id}",
            log_data,
            maxlen=1000
        )
    
    async def _cleanup_all_instances(self):
        """Cleanup all mounted instances."""
        for prefix in list(self.mounted_instances.keys()):
            await self.unmount(prefix)
    
    # === Composite Management Methods ===
    
    async def create_composite(
        self,
        composite_id: str,
        name: str,
        description: str = "",
        user_id: str = None
    ) -> Dict[str, Any]:
        """Create a new composite server instance."""
        composite_data = {
            "id": composite_id,
            "name": name,
            "description": description,
            "user_id": user_id,
            "created_at": datetime.datetime.utcnow().isoformat(),
            "status": "active",
            "mounted_instances": []
        }
        
        # Store composite metadata in Redis
        await self.redis_client.hset(
            f"mcp:composite:{composite_id}",
            mapping=composite_data
        )
        
        logger.info(f"Created composite server {composite_id} for user {user_id}")
        return composite_data
    
    async def get_composite_info(self, composite_id: str) -> Dict[str, Any]:
        """Get information about a composite server."""
        composite_data = await self.redis_client.hgetall(f"mcp:composite:{composite_id}")
        if not composite_data:
            raise ValueError(f"Composite server {composite_id} not found")
        
        # Add current status
        status = await self.get_status()
        composite_data.update({
            "current_status": status,
            "mounted_prefixes": list(self.mounted_instances.keys())
        })
        
        return composite_data
    
    async def mount_instance(
        self,
        composite_id: str,
        instance_id: str,
        prefix: str,
        transport: MCPSaaSTransport
    ) -> bool:
        """Mount an instance to a specific composite server."""
        # Verify composite exists
        composite_data = await self.redis_client.hgetall(f"mcp:composite:{composite_id}")
        if not composite_data:
            raise ValueError(f"Composite server {composite_id} not found")
        
        # Mount the instance
        success = await self.mount(instance_id, prefix, transport)
        
        if success:
            # Update composite metadata
            mounted_instances = json.loads(composite_data.get("mounted_instances", "[]"))
            mounted_instances.append({
                "instance_id": instance_id,
                "prefix": prefix,
                "mounted_at": datetime.datetime.utcnow().isoformat()
            })
            
            await self.redis_client.hset(
                f"mcp:composite:{composite_id}",
                "mounted_instances",
                json.dumps(mounted_instances)
            )
            
            logger.info(f"Mounted {instance_id} to composite {composite_id} with prefix {prefix}")
        
        return success
