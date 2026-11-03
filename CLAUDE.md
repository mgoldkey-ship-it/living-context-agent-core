# CLAUDE.md — Project Rules & Context

## Overview
`living-context-agent-core` — референсное backend-ядро для мультиагентных систем с контролем контекста, версионной живой документацией (`INDEX.md` + `STATE.json` + изоляция `_archive/`) и безопасной фабрикой узких агентов.

## Key Architectural Invariants
1. **Cold-Start Hydration (`POST /v1/context/hydrate`):** агенты получают только актуальные документы (`status: active`) из `domains/` в рамках заданного `token_budget`. Архивные ревизии из `_archive/` никогда не попадают в оперативный контекст.
2. **Write-Through Doc Gate (`POST /v1/tasks/commit`):** задача не переходит в `DONE` без валидного `doc_patch` (либо обоснованного `no_doc_impact=True`). Старая ревизия переносится в `_archive/..._vN.md` со статусом `superseded`.
3. **Least-Privilege Agent Spawning (`POST /v1/agents/match-or-spawn`):** динамически создаваемые агенты стартуют со статусом `ephemeral` и могут запрашивать только инструменты из белого списка `PERMITTED_TOOL_CATALOG`.

## Commands
- Запуск тестов: `pytest -v`
- Локальный запуск сервера: `uvicorn app.main:app --reload --port 8000`
- Запуск в Docker: `docker compose up --build -d`
