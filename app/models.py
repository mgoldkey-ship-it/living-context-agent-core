from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class DocStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class DocPassport(BaseModel):
    doc_id: str = Field(..., min_length=2, max_length=80, pattern=r"^[a-z0-9_/-]+$")
    domain: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z0-9_]+$")
    version: int = Field(default=1, ge=1)
    status: DocStatus = DocStatus.ACTIVE
    supersedes_version: Optional[int] = None
    updated_by: str = Field(..., min_length=2, max_length=60)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    summary: str = Field(..., min_length=5, max_length=180)


class HydrateRequest(BaseModel):
    task_goal: str = Field(..., min_length=3, max_length=1000)
    domains: List[str] = Field(default_factory=list)
    token_budget: int = Field(default=5000, ge=800, le=16000)


class ContextDocumentChunk(BaseModel):
    path: str
    version: int
    estimated_tokens: int
    content: str


class ContextPack(BaseModel):
    index_map: str
    active_state: Dict
    loaded_documents: List[ContextDocumentChunk]
    total_estimated_tokens: int
    token_budget: int
    truncated: bool = False


class DocPatch(BaseModel):
    no_doc_impact: bool = False
    no_impact_reason: Optional[str] = Field(default=None, max_length=300)
    domain: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_]+$")
    doc_name: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_]+$")
    summary: Optional[str] = Field(default=None, min_length=5, max_length=180)
    new_content: Optional[str] = Field(default=None, min_length=5, max_length=12000)

    @field_validator("no_impact_reason")
    @classmethod
    def check_reason(cls, v, info):
        if info.data.get("no_doc_impact") and (not v or len(v.strip()) < 5):
            raise ValueError("no_impact_reason is required when no_doc_impact=True")
        return v


class TaskCommitRequest(BaseModel):
    task_id: str = Field(..., min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    agent_id: str = Field(..., min_length=2, max_length=60, pattern=r"^[a-zA-Z0-9_-]+$")
    result_summary: str = Field(..., min_length=3, max_length=2000)
    doc_patch: DocPatch


class TaskCommitResponse(BaseModel):
    task_id: str
    status: Literal["DONE"]
    committed_doc_path: Optional[str] = None
    new_version: Optional[int] = None
    archived_path: Optional[str] = None
    idempotent_replay: bool = False


class AgentBlueprint(BaseModel):
    agent_id: str = Field(..., pattern=r"^[a-z0-9_]+$")
    role: str = Field(..., min_length=3, max_length=120)
    capabilities: List[str] = Field(..., min_length=1)
    allowed_tools: List[str] = Field(default_factory=list)
    context_scope: List[str] = Field(..., min_length=1)
    lifecycle: Literal["ephemeral", "persistent"] = "ephemeral"
    model_tier: Literal["fast", "balanced", "reasoning"] = "balanced"


class MatchOrSpawnRequest(BaseModel):
    task_description: str = Field(..., min_length=5, max_length=1000)
    required_capabilities: List[str] = Field(..., min_length=1)
    requested_tools: List[str] = Field(default_factory=list)
    target_domains: List[str] = Field(default_factory=lambda: ["projects"])


class MatchOrSpawnResponse(BaseModel):
    action: Literal["reused_existing", "spawned_ephemeral"]
    match_score: float
    blueprint: AgentBlueprint
