"""Pydantic models for session CRUD API requests/responses."""

from pydantic import BaseModel, Field

from shared.enums import SessionType


class SessionCreate(BaseModel):
    """Request to create a new trading session."""
    name: str
    session_type: SessionType
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT"])
    # For real sessions
    api_key: str = ""
    api_secret: str = ""
    testnet: bool = True
    # For sim sessions
    starting_budget: float = 10000.0


class SessionUpdate(BaseModel):
    """Request to update an existing session."""
    name: str | None = None
    symbols: list[str] | None = None
    api_key: str | None = None
    api_secret: str | None = None
    testnet: bool | None = None
    starting_budget: float | None = None


class SessionInfo(BaseModel):
    """Response model for session details."""
    id: str
    name: str
    session_type: SessionType
    is_simulation: bool
    status: str
    starting_budget: float | None = None
    symbols: list[str] = Field(default_factory=list)
    strategy_class: str | None = None
    created_at: str
