
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
.env
workspace_memory/

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

services:
  agent-core:
    build: .
    ports:
      - "8000:8000"
    environment:
      - MEMORY_ROOT=/srv/app/workspace_memory
      - CORE_API_KEY=${CORE_API_KEY:-change-me-in-prod}
    volumes:
      - agent_memory:/srv/app/workspace_memory
    restart: unless-stopped

volumes:
  agent_memory:

FROM python:3.12-slim

WORKDIR /srv/app

RUN adduser --disabled-password --gecos "" appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /srv/app/workspace_memory && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

[project]
name = "living-context-agent-core"
version = "1.0.0"
description = "Reference FastAPI multi-agent backend with Living Documentation, Cold-Start Hydration, and least-privilege Agent Spawning"
requires-python = ">=3.11"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

# Living-Context Agent Core

Референсное **FastAPI**-ядро для мультиагентного AI-ассистента с жёстким контролем контекста, атомарной живой документацией и безопасным самосозданием узких агентов.

## Что решает этот сервис

1. **Защита от деградации контекста и устаревших знаний (`LivingMemoryStore`):**
   - **L0 (`INDEX.md` + `STATE.json`):** компактная карта доменов и слепок состояния.
   - **L1 (`domains/<domain>/<doc>.md`):** атомарные документы, где хранится **только текущая актуальная версия** (`status: active`).
   - **Архив ревизий (`_archive/`):** при обновлении правила предыдущая версия автоматически переносится в `_archive/` со статусом `superseded` — рабочие агенты не путают старые и новые версии, но история полностью сохранена.
   - **Бюджет токенов:** эндпоинт `/v1/context/hydrate` собирает контекст строго в пределах `token_budget` (по умолчанию до `5000` токенов).

2. **Обязательный шлюз обновления документации (`Doc Steward Gate`):**
   - Эндпоинт `/v1/tasks/commit` блокирует завершение задачи (`422`), если агент не передал валидный `doc_patch` (или обоснованный `no_doc_impact`).
   - Встроена **идемпотентность по `task_id`** (защита от повторных вебхуков и дублей версий).

3. **Реестр и Фабрика агентов с принципом минимальных привилегий (`AgentRegistryAndFactory`):**
   - Сначала ищет подходящего постоянного агента по `capability_score` (`>= 0.80`).
   - Если задача новая — создаёт временного (`ephemeral`) специалиста со строгим паспортом `AgentBlueprint`.
   - Любая попытка запросить инструмент вне белого списка блокируется (`403 Forbidden`).

---

## Структура проекта

```text
living-context-agent-core/
├── app/
│   ├── main.py           # FastAPI роуты + проверка X-API-Key
│   ├── models.py         # Строгие Pydantic v2 контракты
│   ├── memory_store.py   # INDEX.md, STATE.json, версионирование и Hydration
│   └── agent_factory.py  # Реестр компетенций и безопасный спавн агентов
├── tests/
│   └── test_core.py      # Автотесты (версионность, идемпотентность, права, 401/403/422)
├── CLAUDE.md             # Правила репозитория для AI-агентов разработки
├── Dockerfile            # Non-root контейнер на Python 3.12-slim
├── docker-compose.yml    # Быстрый запуск с volume для памяти
└── requirements.txt
```

---

## Быстрый старт

### Через Docker Compose
```bash
CORE_API_KEY=my-secret-key docker compose up --build -d
curl http://localhost:8000/health
```

### Локально и запуск тестов
```bash
pip install -r requirements.txt
pytest -v
uvicorn app.main:app --reload --port 8000
```

Интерактивная документация Swagger доступна после старта по адресу: `http://localhost:8000/docs`.

fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.8.0
pytest>=8.2.0
httpx>=0.27.0
