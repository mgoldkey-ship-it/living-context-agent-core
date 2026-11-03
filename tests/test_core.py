import pytest
from fastapi.testclient import TestClient

from app.main import create_app

AUTH = {"X-API-Key": "test-secret"}


@pytest.fixture()
def client(tmp_path):
    app = create_app(memory_dir=tmp_path / "memory", api_key="test-secret")
    return TestClient(app)


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_unauthorized_rejected(client):
    res = client.post(
        "/v1/context/hydrate",
        json={"task_goal": "Проверить проект", "domains": []},
    )
    assert res.status_code == 401


def test_doc_steward_versioning_and_archive_isolation(client, tmp_path):
    # 1. Commit v1 of a domain document
    r1 = client.post(
        "/v1/tasks/commit",
        headers=AUTH,
        json={
            "task_id": "task-101",
            "agent_id": "architect_agent",
            "result_summary": "Описаны базовые тарифы v1",
            "doc_patch": {
                "no_doc_impact": False,
                "domain": "projects",
                "doc_name": "pricing_rules",
                "summary": "Актуальные правила расчёта тарифов",
                "new_content": "Базовый тариф = 1000 руб.",
            },
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["new_version"] == 1
    assert d1["archived_path"] is None
    assert d1["idempotent_replay"] is False

    # 2. Idempotency check: repeating same task_id must NOT create v2 duplicate
    r_dup = client.post(
        "/v1/tasks/commit",
        headers=AUTH,
        json={
            "task_id": "task-101",
            "agent_id": "architect_agent",
            "result_summary": "Повторный вебхук",
            "doc_patch": {
                "no_doc_impact": False,
                "domain": "projects",
                "doc_name": "pricing_rules",
                "summary": "Актуальные правила расчёта тарифов",
                "new_content": "Базовый тариф = 1000 руб.",
            },
        },
    )
    assert r_dup.status_code == 200
    assert r_dup.json()["idempotent_replay"] is True
    assert r_dup.json()["new_version"] == 1

    # 3. Commit v2 update: v1 must move to _archive/ with status: superseded
    r2 = client.post(
        "/v1/tasks/commit",
        headers=AUTH,
        json={
            "task_id": "task-102",
            "agent_id": "architect_agent",
            "result_summary": "Обновлён тариф до 1500 руб.",
            "doc_patch": {
                "no_doc_impact": False,
                "domain": "projects",
                "doc_name": "pricing_rules",
                "summary": "Обновлённые правила тарифов (v2)",
                "new_content": "Базовый тариф = 1500 руб. Старый тариф отменён.",
            },
        },
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["new_version"] == 2
    assert d2["archived_path"] == "_archive/projects/pricing_rules_v1.md"

    arch_file = tmp_path / "memory" / "_archive" / "projects" / "pricing_rules_v1.md"
    assert arch_file.exists()
    assert "status: superseded" in arch_file.read_text(encoding="utf-8")

    # 4. Hydrate context: agent must ONLY see v2 (1500 руб.), never superseded v1
    hyd = client.post(
        "/v1/context/hydrate",
        headers=AUTH,
        json={"task_goal": "Узнать правила тарифов", "domains": ["projects"], "token_budget": 5000},
    )
    assert hyd.status_code == 200
    pack = hyd.json()
    assert len(pack["loaded_documents"]) == 1
    assert pack["loaded_documents"][0]["version"] == 2
    assert "1500 руб." in pack["loaded_documents"][0]["content"]
    assert "1000 руб." not in pack["loaded_documents"][0]["content"]


def test_commit_blocked_without_valid_doc_patch(client):
    # Agent tries to finish task without doc_patch fields and without no_doc_impact reason
    res = client.post(
        "/v1/tasks/commit",
        headers=AUTH,
        json={
            "task_id": "task-bad",
            "agent_id": "lazy_agent",
            "result_summary": "Сделал задачу, доки не трогал",
            "doc_patch": {"no_doc_impact": False},
        },
    )
    assert res.status_code == 422


def test_agent_registry_reuse_vs_least_privilege_spawn(client):
    # Case A: Existing support capability -> reuse persistent agent
    reuse_res = client.post(
        "/v1/agents/match-or-spawn",
        headers=AUTH,
        json={
            "task_description": "Разобрать входящие FAQ вопросы из CRM",
            "required_capabilities": ["support", "triage", "crm"],
            "requested_tools": ["crm_read"],
        },
    )
    assert reuse_res.status_code == 200
    assert reuse_res.json()["action"] == "reused_existing"
    assert reuse_res.json()["blueprint"]["agent_id"] == "support_triage_agent"

    # Case B: Novel capability -> spawn ephemeral agent
    spawn_res = client.post(
        "/v1/agents/match-or-spawn",
        headers=AUTH,
        json={
            "task_description": "Сверка таможенных кодов поставщиков",
            "required_capabilities": ["customs", "logistics_audit"],
            "requested_tools": ["web_search", "analytics_sql_readonly"],
            "target_domains": ["projects"],
        },
    )
    assert spawn_res.status_code == 200
    assert spawn_res.json()["action"] == "spawned_ephemeral"
    assert spawn_res.json()["blueprint"]["lifecycle"] == "ephemeral"

    # Case C: Security check — dangerous unapproved tool must be rejected with 403
    danger_res = client.post(
        "/v1/agents/match-or-spawn",
        headers=AUTH,
        json={
            "task_description": "Подозрительная задача",
            "required_capabilities": ["custom_ops"],
            "requested_tools": ["raw_shell_root_exec"],
        },
    )
    assert danger_res.status_code == 403
