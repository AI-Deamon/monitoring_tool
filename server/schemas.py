from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import math


def validate_duration_seconds(v, max_seconds=86400):
    """
    Validate duration is a sane number.
    
    Prevents:
    - NaN, Infinity
    - Negative values
    - Values exceeding max_seconds (default 24 hours)
    """
    if v is None:
        return 0
    
    # Handle string input
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            raise ValueError(f"Cannot convert '{v}' to number")
    
    # Check for NaN/Infinity
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise ValueError('Duration cannot be NaN or Infinity')
    
    # Range validation
    if v < 0:
        raise ValueError('Duration cannot be negative')
    if v > max_seconds:
        raise ValueError(f'Duration cannot exceed {max_seconds} seconds ({max_seconds/3600:.1f} hours)')
    
    return int(v)


class RegisterSchema(BaseModel):
    """Agent registration request."""
    agent_id: str = Field(..., min_length=1)
    agent_name: Optional[str] = None  # Custom display name
    local_agent_key: Optional[str] = None
    hostname: Optional[str] = None
    
    # OS Detection (old + new fields)
    os: Optional[str] = None  # Old format
    os_version: Optional[str] = None  # New: "Windows 11 Pro (Build 22631)"
    os_build: Optional[int] = None  # NEW: 22631
    windows_edition: Optional[str] = None  # NEW: "Pro", "Home", "Enterprise"
    architecture: Optional[str] = None  # NEW: "AMD64", "x86", "ARM64"
    
    # Agent Version (old + new)
    version: Optional[str] = None  # Old format
    agent_version: Optional[str] = None  # New format
    
    def get_os_version(self) -> Optional[str]:
        """Get OS version from either field."""
        return self.os_version or self.os
    
    def get_agent_version(self) -> Optional[str]:
        """Get agent version from either field."""
        return self.agent_version or self.version


class ScreentimeSchema(BaseModel):
    """
    Screen time telemetry with validation.
    
    Validates:
    - Duration fields are within 0-86400 (24 hours)
    - No NaN or Infinity values
    - State is one of: active, idle, locked
    """
    agent_id: str
    username: Optional[str] = None
    timestamp: Optional[str] = None  # ISO8601
    date: Optional[str] = None  # YYYY-MM-DD
    active_seconds: int = Field(0, ge=0, le=86400)
    idle_seconds: int = Field(0, ge=0, le=86400)
    locked_seconds: int = Field(0, ge=0, le=86400)
    current_state: str = 'active'  # active, idle, locked
    
    @validator('active_seconds', 'idle_seconds', 'locked_seconds', pre=True)
    def validate_duration(cls, v):
        return validate_duration_seconds(v, max_seconds=86400)
    
    @validator('current_state')
    def validate_state(cls, v):
        valid_states = {'active', 'idle', 'locked'}
        if v and v.lower() not in valid_states:
            # Default to 'active' if invalid
            return 'active'
        return v.lower() if v else 'active'
    
    class Config:
        extra = 'allow'  # Allow extra fields for backward compatibility


class AppActiveSchema(BaseModel):
    """Active app telemetry (every 30s) with validation."""
    agent_id: str
    username: Optional[str] = None
    timestamp: Optional[str] = None
    app: str
    friendly_name: Optional[str] = None
    category: Optional[str] = 'other'
    window_title: Optional[str] = None
    session_start: Optional[str] = None
    duration_seconds: float = Field(0, ge=0, le=86400)
    is_active: bool = True
    state: Optional[str] = None
    system_state: Optional[str] = None
    
    @validator('duration_seconds', pre=True)
    def validate_duration(cls, v):
        return validate_duration_seconds(v, max_seconds=86400)
    
    class Config:
        extra = 'allow'


class AppSwitchSchema(BaseModel):
    """App switch event (on app change) with validation."""
    agent_id: str
    username: Optional[str] = None
    timestamp: Optional[str] = None
    app: str
    friendly_name: Optional[str] = None
    category: Optional[str] = 'other'
    window_title: Optional[str] = None
    session_start: Optional[str] = None
    session_end: Optional[str] = None
    total_seconds: float = Field(0, ge=0, le=86400)
    is_active: bool = False
    
    @validator('total_seconds', pre=True)
    def validate_duration(cls, v):
        return validate_duration_seconds(v, max_seconds=86400)
    
    class Config:
        extra = 'allow'


class DomainActiveSchema(BaseModel):
    """Active domain telemetry (every 30s) with validation."""
    agent_id: str
    username: Optional[str] = None
    timestamp: Optional[str] = None
    domain: str
    browser: Optional[str] = None
    url: Optional[str] = None
    session_start: Optional[str] = None
    duration_seconds: float = Field(0, ge=0, le=86400)
    is_active: bool = True
    
    @validator('duration_seconds', pre=True)
    def validate_duration(cls, v):
        return validate_duration_seconds(v, max_seconds=86400)
    
    class Config:
        extra = 'allow'


class DomainSwitchSchema(BaseModel):
    """Domain switch event (on navigation) with validation."""
    agent_id: str
    username: Optional[str] = None
    timestamp: Optional[str] = None
    domain: str
    browser: Optional[str] = None
    url: Optional[str] = None
    session_start: Optional[str] = None
    session_end: Optional[str] = None
    total_seconds: float = Field(0, ge=0, le=86400)
    is_active: bool = False
    
    @validator('total_seconds', pre=True)
    def validate_duration(cls, v):
        return validate_duration_seconds(v, max_seconds=86400)
    
    class Config:
        extra = 'allow'


class StateChangeSchema(BaseModel):
    """State change event with validation."""
    agent_id: str
    username: Optional[str] = None
    timestamp: Optional[str] = None
    previous_state: str = 'active'
    current_state: str = 'active'
    duration_seconds: Optional[float] = Field(0, ge=0, le=86400)
    
    @validator('previous_state', 'current_state')
    def validate_state(cls, v):
        valid_states = {'active', 'idle', 'locked', 'unknown'}
        if v and v.lower() not in valid_states:
            return 'active'
        return v.lower() if v else 'active'
    
    @validator('duration_seconds', pre=True)
    def validate_duration(cls, v):
        if v is None:
            return 0
        return validate_duration_seconds(v, max_seconds=86400)
    
    class Config:
        extra = 'allow'


class AppInventorySchema(BaseModel):
    """App inventory update."""
    agent_id: str
    timestamp: str
    total_apps: Optional[int] = None
    inventory_hash: Optional[str] = None
    is_full_inventory: bool = False
    changes: Dict[str, Any] = {}
    apps: List[Dict[str, Any]] = []


class DomainUsageSchema(BaseModel):
    """Batch domain usage."""
    agent_id: Optional[str] = None
    records: List[Dict[str, Any]] = []


class HeartbeatSchema(BaseModel):
    """Heartbeat check."""
    agent_id: Optional[str] = None
    timestamp: Optional[str] = None
    
    class Config:
        extra = 'allow'
