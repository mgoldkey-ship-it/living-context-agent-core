import os
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.agent_factory import AgentRegistryAndFactory
from app.memory_store import LivingMemoryStore
from app.models import (
    AgentBlueprint,
    ContextPack,
    HydrateRequest,
    MatchOrSpawnRequest,
    MatchOrSpawnResponse,
    TaskCommitRequest,
    TaskCommitResponse,
)


def create_app(memory_dir: Path | None = None, api_key: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Living-Context Agent Core",
        description=(
            "Reference backend for multi-agent orchestration with Cold-Start Context "
            "Hydration (INDEX.md + STATE.json), atomic Doc Steward versioning, and "
            "least-privilege dynamic agent spawning."
        ),
        version="1.0.0",
    )

    root_path = memory_dir or Path(os.getenv("MEMORY_ROOT", "./workspace_memory"))
    expected_key = api_key if api_key is not None else os.getenv("CORE_API_KEY", "dev-secret-key")

    store = LivingMemoryStore(root_path)
    factory = AgentRegistryAndFactory()

    def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-API-Key",
            )

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "living-context-agent-core"}

    @app.post(
        "/v1/context/hydrate",
        response_model=ContextPack,
        dependencies=[Depends(verify_api_key)],
    )
    async def hydrate_context(payload: HydrateRequest):
        return store.hydrate_context(
            task_goal=payload.task_goal,
            domains=payload.domains,
            token_budget=payload.token_budget,
        )

    @app.post(
        "/v1/tasks/commit",
        response_model=TaskCommitResponse,
        dependencies=[Depends(verify_api_key)],
    )
    async def commit_task(payload: TaskCommitRequest):
        try:
            doc_path, new_ver, arch_path, replay = store.commit_doc_patch(
                task_id=payload.task_id,
                agent_id=payload.agent_id,
                result_summary=payload.result_summary,
                patch=payload.doc_patch,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return TaskCommitResponse(
            task_id=payload.task_id,
            status="DONE",
            committed_doc_path=doc_path,
            new_version=new_ver,
            archived_path=arch_path,
            idempotent_replay=replay,
        )

    @app.get(
        "/v1/agents",
        response_model=list[AgentBlueprint],
        dependencies=[Depends(verify_api_key)],
    )
    async def list_agents():
        return factory.list_agents()

    @app.post(
        "/v1/agents/match-or-spawn",
        response_model=MatchOrSpawnResponse,
        dependencies=[Depends(verify_api_key)],
    )
    async def match_or_spawn(payload: MatchOrSpawnRequest):
        try:
            return factory.match_or_spawn(payload)
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc

    return app


app = create_app()
