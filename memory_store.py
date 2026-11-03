import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.models import (
    ContextDocumentChunk,
    ContextPack,
    DocPassport,
    DocPatch,
    DocStatus,
)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (~3.5 chars per token for mixed RU/EN markdown)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 3.5))


class LivingMemoryStore:
    """
    Atomic filesystem-backed Living Documentation store:
      memory_root/
        INDEX.md        (L0 map)
        STATE.json      (L0 operational snapshot)
        domains/        (L1 active documents only)
        _archive/       (Superseded historical versions)
    """

    def __init__(self, root_dir: Path):
        self.root = Path(root_dir)
        self.domains_dir = self.root / "domains"
        self.archive_dir = self.root / "_archive"
        self.index_file = self.root / "INDEX.md"
        self.state_file = self.root / "STATE.json"
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        self.domains_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            initial_state = {
                "active_tasks": [],
                "completed_task_commits": {},
                "doc_registry": {},
            }
            self.state_file.write_text(
                json.dumps(initial_state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if not self.index_file.exists():
            self._rebuild_index()

    def read_state(self) -> Dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def write_state(self, state: Dict) -> None:
        self.state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _rebuild_index(self) -> None:
        state = self.read_state()
        reg: Dict = state.get("doc_registry", {})
        lines = [
            "# INDEX (L0 Living Knowledge Map)",
            "",
            "Актуальные домены и документы (`status: active`):",
            "",
        ]
        if not reg:
            lines.append("- *(база знаний пока пуста)*")
        else:
            for doc_key in sorted(reg.keys()):
                meta = reg[doc_key]
                lines.append(
                    f"- `domains/{doc_key}.md` (v{meta['version']}) — {meta['summary']}"
                )
        self.index_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _render_markdown(passport: DocPassport, body: str) -> str:
        header = [
            "---",
            f"doc_id: {passport.doc_id}",
            f"domain: {passport.domain}",
            f"version: {passport.version}",
            f"status: {passport.status.value}",
            f"supersedes: {passport.supersedes_version or 'none'}",
            f"updated_by: {passport.updated_by}",
            f"updated_at: {passport.updated_at}",
            f"summary: \"{passport.summary}\"",
            "---",
            "",
            body.strip(),
            "",
        ]
        return "\n".join(header)

    def commit_doc_patch(
        self, task_id: str, agent_id: str, result_summary: str, patch: DocPatch
    ) -> Tuple[Optional[str], Optional[int], Optional[str], bool]:
        """
        Doc Steward atomic commit gate:
        - Enforces idempotency by task_id
        - Supersedes previous active file into _archive/
        - Writes new active file and refreshes INDEX.md + STATE.json
        """
        state = self.read_state()
        commits = state.setdefault("completed_task_commits", {})

        # Idempotency check: repeated webhook / retry for same task_id
        if task_id in commits:
            prev = commits[task_id]
            return (
                prev.get("committed_doc_path"),
                prev.get("new_version"),
                prev.get("archived_path"),
                True,
            )

        if patch.no_doc_impact:
            commits[task_id] = {
                "agent_id": agent_id,
                "result_summary": result_summary,
                "no_doc_impact": True,
                "reason": patch.no_impact_reason,
                "committed_doc_path": None,
                "new_version": None,
                "archived_path": None,
            }
            self.write_state(state)
            return None, None, None, False

        if not (patch.domain and patch.doc_name and patch.summary and patch.new_content):
            raise ValueError(
                "domain, doc_name, summary, and new_content are required when no_doc_impact=False"
            )

        doc_key = f"{patch.domain}/{patch.doc_name}"
        reg = state.setdefault("doc_registry", {})
        existing_meta = reg.get(doc_key)

        domain_folder = self.domains_dir / patch.domain
        domain_folder.mkdir(parents=True, exist_ok=True)
        active_file = domain_folder / f"{patch.doc_name}.md"

        archived_rel_path: Optional[str] = None
        if existing_meta and active_file.exists():
            old_ver = existing_meta["version"]
            new_ver = old_ver + 1
            arch_folder = self.archive_dir / patch.domain
            arch_folder.mkdir(parents=True, exist_ok=True)
            arch_file = arch_folder / f"{patch.doc_name}_v{old_ver}.md"

            old_text = active_file.read_text(encoding="utf-8").replace(
                "status: active", f"status: {DocStatus.SUPERSEDED.value}", 1
            )
            arch_file.write_text(old_text, encoding="utf-8")
            archived_rel_path = f"_archive/{patch.domain}/{patch.doc_name}_v{old_ver}.md"
            supersedes = old_ver
        else:
            new_ver = 1
            supersedes = None

        passport = DocPassport(
            doc_id=doc_key,
            domain=patch.domain,
            version=new_ver,
            status=DocStatus.ACTIVE,
            supersedes_version=supersedes,
            updated_by=agent_id,
            summary=patch.summary,
        )
        active_file.write_text(
            self._render_markdown(passport, patch.new_content), encoding="utf-8"
        )

        committed_rel = f"domains/{doc_key}.md"
        reg[doc_key] = {
            "version": new_ver,
            "summary": patch.summary,
            "updated_by": agent_id,
            "updated_at": passport.updated_at,
        }
        commits[task_id] = {
            "agent_id": agent_id,
            "result_summary": result_summary,
            "no_doc_impact": False,
            "committed_doc_path": committed_rel,
            "new_version": new_ver,
            "archived_path": archived_rel_path,
        }
        self.write_state(state)
        self._rebuild_index()
        return committed_rel, new_ver, archived_rel_path, False

    def hydrate_context(
        self, task_goal: str, domains: List[str], token_budget: int = 5000
    ) -> ContextPack:
        """
        Cold-Start Hydration Protocol:
        1. Always loads L0 (INDEX.md + compact STATE snapshot)
        2. Loads ONLY active L1 docs from requested domains (never _archive/)
        3. Enforces hard token_budget ceiling
        """
        index_text = self.index_file.read_text(encoding="utf-8")
        full_state = self.read_state()
        compact_state = {
            "active_tasks": full_state.get("active_tasks", []),
            "known_docs_count": len(full_state.get("doc_registry", {})),
        }
        used_tokens = estimate_tokens(index_text) + estimate_tokens(
            json.dumps(compact_state, ensure_ascii=False)
        )

        reg = full_state.get("doc_registry", {})
        target_domains = set(domains) if domains else {k.split("/")[0] for k in reg}

        loaded: List[ContextDocumentChunk] = []
        truncated = False

        # Prioritize docs whose key or summary overlaps with task_goal keywords
        goal_words = {w.lower() for w in task_goal.split() if len(w) > 3}

        def relevance(item):
            doc_key, meta = item
            text_blob = f"{doc_key} {meta.get('summary', '')}".lower()
            hits = sum(1 for w in goal_words if w in text_blob)
            return (-hits, doc_key)

        for doc_key, meta in sorted(reg.items(), key=relevance):
            dom = doc_key.split("/")[0]
            if dom not in target_domains:
                continue
            file_path = self.domains_dir / f"{doc_key}.md"
            if not file_path.exists():
                continue
            content = file_path.read_text(encoding="utf-8")
            doc_tokens = estimate_tokens(content)
            if used_tokens + doc_tokens <= token_budget:
                loaded.append(
                    ContextDocumentChunk(
                        path=f"domains/{doc_key}.md",
                        version=meta["version"],
                        estimated_tokens=doc_tokens,
                        content=content,
                    )
                )
                used_tokens += doc_tokens
            else:
                truncated = True

        return ContextPack(
            index_map=index_text,
            active_state=compact_state,
            loaded_documents=loaded,
            total_estimated_tokens=used_tokens,
            token_budget=token_budget,
            truncated=truncated,
        )
