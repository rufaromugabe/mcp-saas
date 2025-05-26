#!/usr/bin/env python3
"""
Simple script to run the MCP SaaS application for development/testing
"""
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Set environment variables for local development
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./mcp_saas.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ENVIRONMENT", "development")

if __name__ == "__main__":
    import uvicorn
    
    print("🚀 Starting MCP SaaS application in development mode...")
    print("📊 Dashboard will be available at: http://localhost:8000/docs")
    print("🔗 Health check: http://localhost:8000/health")    
    print("⚠️  Note: This will use SQLite database for local testing")
    print()
    
    try:
        # Use import string for reload functionality
        uvicorn.run(
            "app_fastmcp:app",
            host="127.0.0.1",
            port=8000,
            reload=True,
            log_level="info",
            access_log=True
        )
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("🔧 Make sure all dependencies are installed: pip install -r requirements.txt")
    except Exception as e:
        print(f"❌ Failed to start application: {e}")
        sys.exit(1)
