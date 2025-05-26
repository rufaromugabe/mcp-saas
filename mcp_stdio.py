import asyncio
import json
import logging
import os
import subprocess
from typing import AsyncGenerator, Dict, Any, Optional, List
import redis.asyncio as redis
from dataclasses import dataclass, asdict
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

@dataclass
class MCPMessage:
    id: str
    method: str
    params: Dict[str, Any]
    timestamp: datetime
    instance_id: str

@dataclass
class MCPResponse:
    id: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None

class MCPStdioWrapper:
    """Wrapper to handle MCP server communication via stdio"""
    def __init__(self, instance_id: str, command: str, cwd: str = None, env: Dict[str, str] = None):
        self.instance_id = instance_id
        self.command = command
        self.cwd = cwd
        self.env = env or {}
        self.process = None
        self.message_queue = asyncio.Queue()
        self.response_handlers = {}
        self.event_subscribers = []
        
    async def start(self):
        """Start the MCP server process"""
        try:
            # Merge environment variables with system environment
            process_env = os.environ.copy()
            process_env.update(self.env)
            
            self.process = await asyncio.create_subprocess_shell(
                self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                env=process_env
            )
            
            # Start background tasks for handling I/O
            asyncio.create_task(self._handle_stdout())
            asyncio.create_task(self._handle_stderr())
            asyncio.create_task(self._process_message_queue())
            
            logger.info(f"Started MCP server for instance {self.instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return False
    
    async def _handle_stdout(self):
        """Handle stdout from MCP server"""
        try:
            while self.process and not self.process.stdout.at_eof():
                line = await self.process.stdout.readline()
                if line:
                    try:
                        data = json.loads(line.decode().strip())
                        await self._handle_mcp_message(data)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON from MCP server: {e}")
                        # Forward raw output as event
                        await self._emit_event({
                            'type': 'raw_output',
                            'data': line.decode().strip(),
                            'timestamp': datetime.utcnow().isoformat()
                        })
        except Exception as e:
            logger.error(f"Error handling stdout: {e}")
    
    async def _handle_stderr(self):
        """Handle stderr from MCP server"""
        try:
            while self.process and not self.process.stderr.at_eof():
                line = await self.process.stderr.readline()
                if line:
                    error_msg = line.decode().strip()
                    logger.warning(f"MCP server stderr: {error_msg}")
                    await self._emit_event({
                        'type': 'error',
                        'message': error_msg,
                        'timestamp': datetime.utcnow().isoformat()
                    })
        except Exception as e:
            logger.error(f"Error handling stderr: {e}")
    
    async def _handle_mcp_message(self, data: Dict[str, Any]):
        """Handle incoming MCP messages"""
        try:
            if 'id' in data:
                # This is a response to a previous request
                if data['id'] in self.response_handlers:
                    handler = self.response_handlers.pop(data['id'])
                    if handler and not handler.done():
                        handler.set_result(MCPResponse(
                            id=data['id'],
                            result=data.get('result'),
                            error=data.get('error'),
                            timestamp=datetime.utcnow()
                        ))
            else:
                # This is an event/notification from the server
                await self._emit_event({
                    'type': 'notification',
                    'method': data.get('method'),
                    'params': data.get('params'),
                    'timestamp': datetime.utcnow().isoformat()
                })
                
        except Exception as e:
            logger.error(f"Error handling MCP message: {e}")
    
    async def _emit_event(self, event_data: Dict[str, Any]):
        """Emit event to all subscribers"""
        event_data['instance_id'] = self.instance_id
        
        # Add to message queue for SSE streaming
        await self.message_queue.put(event_data)
        
        # Notify direct subscribers
        for subscriber in self.event_subscribers[:]:  # Copy list to avoid modification issues
            try:
                if hasattr(subscriber, '__call__'):
                    await subscriber(event_data)
            except Exception as e:
                logger.error(f"Error notifying subscriber: {e}")
                self.event_subscribers.remove(subscriber)
    
    async def _process_message_queue(self):
        """Process messages from the queue"""
        # This could be extended to handle message persistence, filtering, etc.
        pass
    
    async def send_request(self, method: str, params: Dict[str, Any] = None) -> MCPResponse:
        """Send request to MCP server and wait for response"""
        if not self.process:
            raise Exception("MCP server not started")
        
        message_id = str(uuid.uuid4())
        message = {
            'jsonrpc': '2.0',
            'id': message_id,
            'method': method,
            'params': params or {}
        }
        
        # Create future for response
        response_future = asyncio.Future()
        self.response_handlers[message_id] = response_future
        
        try:
            # Send message to stdin
            message_json = json.dumps(message) + '\n'
            self.process.stdin.write(message_json.encode())
            await self.process.stdin.drain()
            
            # Wait for response with timeout
            response = await asyncio.wait_for(response_future, timeout=30.0)
            return response
            
        except asyncio.TimeoutError:
            self.response_handlers.pop(message_id, None)
            raise Exception(f"Request {message_id} timed out")
        except Exception as e:
            self.response_handlers.pop(message_id, None)
            raise Exception(f"Failed to send request: {e}")
    
    async def send_notification(self, method: str, params: Dict[str, Any] = None):
        """Send notification to MCP server (no response expected)"""
        if not self.process:
            raise Exception("MCP server not started")
        
        message = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {}
        }
        
        try:
            message_json = json.dumps(message) + '\n'
            self.process.stdin.write(message_json.encode())
            await self.process.stdin.drain()
        except Exception as e:
            raise Exception(f"Failed to send notification: {e}")
    
    def subscribe_to_events(self, callback):
        """Subscribe to events from the MCP server"""
        self.event_subscribers.append(callback)
    
    def unsubscribe_from_events(self, callback):
        """Unsubscribe from events"""
        if callback in self.event_subscribers:
            self.event_subscribers.remove(callback)
    
    async def get_event_stream(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Get async generator for SSE streaming"""
        while True:
            try:
                event = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                yield {
                    'type': 'heartbeat',
                    'timestamp': datetime.utcnow().isoformat(),
                    'instance_id': self.instance_id
                }
            except Exception as e:
                logger.error(f"Error in event stream: {e}")
                yield {
                    'type': 'error',
                    'message': str(e),
                    'timestamp': datetime.utcnow().isoformat(),
                    'instance_id': self.instance_id
                }
    
    async def stop(self):
        """Stop the MCP server process"""
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(f"Error stopping MCP server: {e}")
            finally:
                self.process = None
                logger.info(f"Stopped MCP server for instance {self.instance_id}")

class MCPInstanceManager:
    """Enhanced manager for MCP instances with Redis backing"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis = None
        self.instances: Dict[str, MCPStdioWrapper] = {}
    
    async def initialize(self):
        """Initialize Redis connection"""
        self.redis = await redis.from_url(self.redis_url)
    async def create_instance(
        self, 
        instance_id: str, 
        command: str, 
        args: List[str] = None, 
        cwd: str = None, 
        env: Dict[str, str] = None
    ) -> MCPStdioWrapper:
        """Create and start new MCP instance"""
        if instance_id in self.instances:
            raise Exception(f"Instance {instance_id} already exists")
        
        # Build full command with args
        if args:
            full_command = f"{command} {' '.join(args)}"
        else:
            full_command = command
        
        wrapper = MCPStdioWrapper(instance_id, full_command, cwd, env)
        
        if await wrapper.start():
            self.instances[instance_id] = wrapper
            
            # Store instance metadata in Redis
            if self.redis:
                await self.redis.hset(
                    f"mcp:instance:{instance_id}",
                    mapping={
                        'command': command,
                        'args': ' '.join(args) if args else '',
                        'cwd': cwd or '',
                        'env': json.dumps(env) if env else '{}',
                        'created_at': datetime.utcnow().isoformat(),
                        'status': 'running'
                    }
                )
            
            return wrapper
        else:
            raise Exception(f"Failed to start MCP instance {instance_id}")
    
    async def get_instance(self, instance_id: str) -> Optional[MCPStdioWrapper]:
        """Get existing MCP instance"""
        return self.instances.get(instance_id)
    
    async def stop_instance(self, instance_id: str):
        """Stop and remove MCP instance"""
        if instance_id in self.instances:
            wrapper = self.instances[instance_id]
            await wrapper.stop()
            del self.instances[instance_id]
            
            # Update status in Redis
            if self.redis:
                await self.redis.hset(
                    f"mcp:instance:{instance_id}",
                    'status', 'stopped'
                )
    
    async def list_instances(self) -> Dict[str, Dict[str, Any]]:
        """List all active instances"""
        result = {}
        for instance_id, wrapper in self.instances.items():
            if self.redis:
                metadata = await self.redis.hgetall(f"mcp:instance:{instance_id}")
                result[instance_id] = {
                    k.decode() if isinstance(k, bytes) else k: 
                    v.decode() if isinstance(v, bytes) else v 
                    for k, v in metadata.items()
                }
            else:
                result[instance_id] = {'status': 'running'}
        
        return result
    
    async def cleanup(self):
        """Cleanup all instances and connections"""
        for instance_id in list(self.instances.keys()):
            await self.stop_instance(instance_id)
        
        if self.redis:
            await self.redis.close()
