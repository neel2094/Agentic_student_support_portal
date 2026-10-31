"""Pydantic models: tool inputs and the agent's result."""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class TicketInput(BaseModel):
    category: Literal["fee", "scholarship", "course_change", "portal", "other"]
    description: str = Field(min_length=5, max_length=300)


class MemoryInput(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=150)


class AgentResult(BaseModel):
    answer: str
    tools_called: list[dict] = []        # [{name, args, ok}]
    chunks: list[dict] = []              # retrieved policy evidence
    memory_used: list[int] = []          # memory record ids placed in the context
    llm_seconds: float = 0.0
    total_seconds: float = 0.0
    input_tokens: Optional[int] = None   # None = unavailable
    output_tokens: Optional[int] = None
    trace_id: Optional[str] = None
    error: Optional[str] = None
    suggested_questions: list[str] = []  # follow-up buttons that can be answered properly
