#!/usr/bin/env python3
"""
Startup script for MCP SaaS - handles database initialization and other setup tasks
"""
import asyncio
import os
import sys
import logging
from pathlib import Path

# Add the current directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from database import engine, Base, SessionLocal
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_tables():
    """Create database tables if they don't exist"""
    try:
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables created successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create database tables: {e}")
        return False

async def check_database_connection():
    """Check if database connection is working"""
    try:
        db = SessionLocal()
        result = db.execute(text("SELECT 1"))
        db.close()
        logger.info("✅ Database connection successful")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

async def create_directories():
    """Create necessary directories"""
    directories = [
        Path(os.getenv('TEMP_DIR', '/app/temp')),
        Path(os.getenv('LOGS_DIR', '/app/logs')),
        Path(os.getenv('INSTANCE_DIR', '/app/instances'))
    ]
    
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Created directory: {directory}")
        except Exception as e:
            logger.error(f"❌ Failed to create directory {directory}: {e}")
            return False
    
    return True

async def main():
    """Main startup sequence"""
    logger.info("🚀 Starting MCP SaaS initialization...")
    
    # Check database connection
    if not await check_database_connection():
        sys.exit(1)
    
    # Create tables
    if not await create_tables():
        sys.exit(1)
    
    # Create directories
    if not await create_directories():
        sys.exit(1)
    
    logger.info("✅ MCP SaaS initialization completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
