from sqlalchemy import create_engine, Column, String, Boolean, DateTime, Text, Integer, DECIMAL, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator, CHAR
import uuid
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://mcp_user:mcp_password@postgres:5432/mcp_saas"
)

# Custom UUID type that works with both PostgreSQL and SQLite
class UUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def __init__(self, as_uuid=False, *args, **kwargs):
        # Handle the as_uuid parameter but don't pass it to the parent
        self.as_uuid = as_uuid
        # Remove as_uuid from kwargs before passing to parent
        kwargs.pop('as_uuid', None)
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PostgresUUID(as_uuid=self.as_uuid))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value) if not self.as_uuid else value
        else:
            if not isinstance(value, uuid.UUID):
                return str(value)
            else:
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if dialect.name == 'postgresql' and self.as_uuid:
                return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
            elif not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            return value

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    instances = relationship("MCPInstance", back_populates="user")

class MCPInstance(Base):
    __tablename__ = "mcp_instances"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)  # Allow null for now
    name = Column(String(255), nullable=False)
    language = Column(String(50), nullable=False)
    entry_point = Column(String(500), nullable=False)
    source_type = Column(String(50), nullable=False)
    source_url = Column(Text, nullable=True)
    command = Column(Text, nullable=False)
    working_directory = Column(Text, nullable=True)
    environment_vars = Column(JSON, default={})
    status = Column(String(50), default='stopped')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_started_at = Column(DateTime(timezone=True), nullable=True)
    last_stopped_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="instances")

class MCPInstanceLog(Base):
    __tablename__ = "mcp_instance_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    log_level = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    log_metadata = Column(JSON, default={})

class MCPInstanceMetrics(Base):
    __tablename__ = "mcp_instance_metrics"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    cpu_usage = Column(DECIMAL(5,2), nullable=True)
    memory_usage = Column(DECIMAL(10,2), nullable=True)
    requests_count = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)
    uptime_seconds = Column(Integer, default=0)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

class Deployment(Base):
    __tablename__ = "deployments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    deployment_config = Column(JSON, nullable=False)
    status = Column(String(50), nullable=False)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    build_logs = Column(Text, nullable=True)

# Database dependency
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Database operations
class DatabaseService:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self.SessionLocal = None
    
    async def initialize(self):
        """Initialize the database connection and create tables"""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        
        self.engine = create_engine(self.database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create tables
        Base.metadata.create_all(bind=self.engine)
    
    def get_session(self):
        """Get a database session"""
        if not self.SessionLocal:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self.SessionLocal()
    async def create_instance(self, instance: MCPInstance) -> MCPInstance:
        """Create a new MCP instance record"""
        with self.get_session() as db:
            db.add(instance)
            db.commit()
            db.refresh(instance)
            return instance
    
    async def get_instance(self, instance_id: str) -> Optional[MCPInstance]:
        """Get an MCP instance by ID"""
        with self.get_session() as db:
            return db.query(MCPInstance).filter(MCPInstance.id == instance_id).first()
    
    async def update_instance_status(self, instance_id: str, status: str):
        """Update instance status"""
        with self.get_session() as db:
            instance = db.query(MCPInstance).filter(MCPInstance.id == instance_id).first()
            if instance:
                instance.status = status
                if status == 'running':
                    instance.last_started_at = func.now()
                elif status == 'stopped':
                    instance.last_stopped_at = func.now()
                db.commit()
    
    async def list_instances(self, user_id: Optional[str] = None) -> list:
        """List all instances, optionally filtered by user"""
        with self.get_session() as db:
            query = db.query(MCPInstance)
            if user_id:
                query = query.filter(MCPInstance.user_id == user_id)
            return query.all()
    
    async def delete_instance(self, instance_id: str):
        """Delete an instance record"""
        with self.get_session() as db:
            instance = db.query(MCPInstance).filter(MCPInstance.id == instance_id).first()
            if instance:
                db.delete(instance)
                db.commit()
    def log_instance_event(self, instance_id: str, level: str, message: str, metadata: dict = None):
        """Log an instance event"""
        log = MCPInstanceLog(
            instance_id=instance_id,
            log_level=level,
            message=message,
            log_metadata=metadata or {}
        )
        self.db.add(log)
        self.db.commit()
    
    def record_metrics(self, instance_id: str, metrics: dict):
        """Record instance metrics"""
        metric = MCPInstanceMetrics(
            instance_id=instance_id,
            **metrics
        )
        self.db.add(metric)
        self.db.commit()
    
    def create_deployment_record(self, deployment_data: dict) -> Deployment:
        """Create a deployment record"""
        deployment = Deployment(**deployment_data)
        self.db.add(deployment)
        self.db.commit()
        self.db.refresh(deployment)
        return deployment
    
    def update_deployment_status(self, deployment_id: str, status: str, error_message: str = None):
        """Update deployment status"""
        deployment = self.db.query(Deployment).filter(Deployment.id == deployment_id).first()
        if deployment:
            deployment.status = status
            if error_message:
                deployment.error_message = error_message
            if status in ['completed', 'failed']:
                deployment.completed_at = func.now()
            self.db.commit()

# Initialize database tables
def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
