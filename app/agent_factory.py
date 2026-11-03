import re
from typing import List

from app.models import AgentBlueprint, MatchOrSpawnRequest, MatchOrSpawnResponse


# Global security catalog of safe, permitted tools (Least-Privilege Whitelist)
PERMITTED_TOOL_CATALOG = {
    "web_search",
    "calendar_read",
    "calendar_propose",
    "crm_read",
    "crm_create_draft",
    "docs_read",
    "docs_propose_patch",
    "analytics_sql_readonly",
}

REUSE_THRESHOLD = 0.80


class AgentRegistryAndFactory:
    """
    Maintains the registry of vetted agents and dynamically synthesizes
    strictly-scoped ephemeral sub-agents when capability score < threshold.
    """

    def __init__(self) -> None:
        self._registry: List[AgentBlueprint] = [
            AgentBlueprint(
                agent_id="support_triage_agent",
                role="Классификация входящих обращений и ответы по базе знаний",
                capabilities=["support", "triage", "faq", "crm"],
                allowed_tools=["docs_read", "crm_read", "docs_propose_patch"],
                context_scope=["playbooks", "profile"],
                lifecycle="persistent",
                model_tier="fast",
            ),
            AgentBlueprint(
                agent_id="project_architect_agent",
                role="Проектирование архитектуры и ведение проектных ADR-решений",
                capabilities=["architecture", "backend", "api", "adr", "planning"],
                allowed_tools=["docs_read", "docs_propose_patch", "web_search"],
                context_scope=["projects", "playbooks"],
                lifecycle="persistent",
                model_tier="reasoning",
            ),
        ]

    def list_agents(self) -> List[AgentBlueprint]:
        return list(self._registry)

    def match_or_spawn(self, req: MatchOrSpawnRequest) -> MatchOrSpawnResponse:
        # Security guardrail: reject any unapproved or dangerous tools (e.g. shell_exec, db_drop)
        illegal = [t for t in req.requested_tools if t not in PERMITTED_TOOL_CATALOG]
        if illegal:
            raise PermissionError(
                f"Requested tools are outside permitted security whitelist: {illegal}"
            )

        req_caps = {c.strip().lower() for c in req.required_capabilities if c.strip()}
        best_agent = None
        best_score = 0.0

        for candidate in self._registry:
            cand_caps = {c.lower() for c in candidate.capabilities}
            overlap = len(req_caps & cand_caps)
            score = overlap / max(1, len(req_caps))
            if score > best_score:
                best_score = score
                best_agent = candidate

        if best_agent and best_score >= REUSE_THRESHOLD:
            return MatchOrSpawnResponse(
                action="reused_existing",
                match_score=round(best_score, 2),
                blueprint=best_agent,
            )

        # Spawn a new strictly-scoped ephemeral agent via Meta-Agent Blueprint rules
        slug_base = "_".join(sorted(req_caps))[:28]
        slug = re.sub(r"[^a-z0-9_]", "_", slug_base).strip("_") or "custom"
        agent_id = f"ephemeral_{slug}_agent"

        safe_tools = sorted(set(req.requested_tools) | {"docs_read", "docs_propose_patch"})
        spawned = AgentBlueprint(
            agent_id=agent_id,
            role=f"Специализированный агент: {req.task_description[:90]}",
            capabilities=sorted(req_caps),
            allowed_tools=safe_tools,
            context_scope=req.target_domains or ["projects"],
            lifecycle="ephemeral",
            model_tier="balanced",
        )
        self._registry.append(spawned)
        return MatchOrSpawnResponse(
            action="spawned_ephemeral",
            match_score=round(best_score, 2),
            blueprint=spawned,
        )
