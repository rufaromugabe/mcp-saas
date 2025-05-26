#!/usr/bin/env python3
"""
Simple health check script for the MCP SaaS application
"""
import asyncio
import sys
import aiohttp

async def health_check():
    """Check if the application is running"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('http://localhost:8000/health', timeout=5) as response:
                if response.status == 200:
                    print("✅ Health check passed")
                    return True
                else:
                    print(f"❌ Health check failed with status: {response.status}")
                    return False
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(health_check())
    sys.exit(0 if result else 1)
