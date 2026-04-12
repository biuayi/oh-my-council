"""Sequential Dispatcher for Phase 1. See spec §3 (single task lifecycle).

Phase 2 replaces this with an asyncio-based concurrent pool and adds
real Codex-escalation on L1 exhaustion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from omc.budget import BudgetTracker
from omc.clients.base import Auditor, CodexClient, WorkerRunner
from omc.gates.path_whitelist import check_paths
from omc.gates.syntax import check_syntax
from omc.models import Interaction
from omc.state import StateEvent, next_state
from omc.store.md import MDLayout
from omc.store.project import ProjectStore


@dataclass(slots=True)
class DispatcherDeps:
    store: ProjectStore
    md: MDLayout
    codex: CodexClient
    worker: WorkerRunner
    auditor: Auditor
    budget: BudgetTracker
    project_source_root: Path  # where worker-produced files actually land


class Dispatcher:
    def __init__(self, deps: DispatcherDeps):
        self.deps = deps

    def run_once(self, task_id: str, requirement: str) -> None:
        """Drive one task from PENDING through to ACCEPTED or BLOCKED."""
        task = self.deps.store.get_task(task_id)
        if task is None:
            raise ValueError(f"task {task_id} not found")

        # 1. Codex produces spec (always once per run_once for simplicity).
        spec = self.deps.codex.produce_spec(task_id, requirement)
        self.deps.md.write_task(task_id, spec.spec_md)
        task.path_whitelist = spec.path_whitelist
        self._record(
            task_id,
            task.project_id,
            "codex",
            "orchestrator",
            "response",
            spec.spec_md,
            tokens_out=spec.tokens_used,
        )

        # 2. Loop: worker write -> gates -> review -> audit.
        while True:
            self.deps.budget.record_attempt(task_id)

            # Transition to RUNNING first so ESCALATION_EXHAUSTED is a valid
            # transition (PENDING -> ESCALATION_EXHAUSTED does not exist in the
            # state machine).
            self._transition(task, StateEvent.WORKER_START)

            if self.deps.budget.l1_exhausted(task_id) and not hasattr(
                self.deps.codex, "dispatch_escalation"
            ):
                self._transition(task, StateEvent.ESCALATION_EXHAUSTED)
                return

            # Worker
            worker_out = self.deps.worker.write(task_id, spec.spec_md)
            self.deps.budget.record_tokens(task_id, worker_out.tokens_used)
            self._record(
                task_id,
                task.project_id,
                "orchestrator",
                "glm5",
                "request",
                spec.spec_md,
                tokens_in=worker_out.tokens_used,
            )

            # L3 token budget check — must happen immediately after recording tokens
            if self.deps.budget.l3_exhausted(task_id):
                self._transition(task, StateEvent.BUDGET_EXCEEDED)
                return

            # Path whitelist (before anything else — cheap reject)
            path_result = check_paths(
                produced=list(worker_out.files.keys()),
                whitelist=task.path_whitelist,
            )
            if not path_result.ok:
                # Try Codex escalation if L1 is exhausted and codex supports it
                if self.deps.budget.l1_exhausted(task_id) and hasattr(
                    self.deps.codex, "dispatch_escalation"
                ):
                    escalated_files = self.deps.codex.dispatch_escalation(
                        task_id, spec.spec_md, worker_out.files
                    )
                    self.deps.budget.record_codex_attempt(task_id)

                    # Re-check gates with escalated files
                    esc_path_result = check_paths(
                        produced=list(escalated_files.keys()),
                        whitelist=task.path_whitelist,
                    )
                    if esc_path_result.ok:
                        # Write the escalated files to disk and continue with them
                        esc_written = self._write_files(escalated_files)
                        esc_syn_result = check_syntax(esc_written)
                        if esc_syn_result.ok:
                            # Escalation succeeded — continue with escalated output
                            worker_out = type(worker_out)(
                                task_id=worker_out.task_id,
                                files=escalated_files,
                                tokens_used=worker_out.tokens_used,
                            )
                            self._transition(task, StateEvent.WORKER_DONE)
                            # Jump directly to review (skip the normal gate block below)
                            review = self.deps.codex.review(
                                task_id, worker_out.files, spec.spec_md
                            )
                            self.deps.budget.record_tokens(task_id, review.tokens_used)
                            self.deps.md.write_review(task_id, review.review_md)
                            self._record(
                                task_id,
                                task.project_id,
                                "codex",
                                "orchestrator",
                                "review",
                                review.review_md,
                                tokens_out=review.tokens_used,
                            )
                            if not review.passed:
                                self._transition(task, StateEvent.REVIEW_FAIL)
                                continue
                            self._transition(task, StateEvent.REVIEW_PASS)

                            # Audit
                            audit = self.deps.auditor.audit(task_id, worker_out.files)
                            self.deps.budget.record_tokens(task_id, audit.tokens_used)
                            self.deps.md.write_audit(task_id, audit.audit_md)
                            self._record(
                                task_id,
                                task.project_id,
                                "glm5",
                                "orchestrator",
                                "audit",
                                audit.audit_md,
                                tokens_out=audit.tokens_used,
                            )
                            if not audit.passed:
                                self._transition(task, StateEvent.AUDIT_FAIL)
                                continue
                            self._transition(task, StateEvent.AUDIT_PASS)
                            return

                    # Escalated files still failed — check L2
                    if self.deps.budget.l2_exhausted(task_id):
                        self._transition(task, StateEvent.ESCALATION_EXHAUSTED)
                        return
                    # L2 not yet exhausted — fall through to WORKER_FAIL and retry
                    self._transition(task, StateEvent.WORKER_FAIL)
                    continue

                # No escalation available — discard and retry worker
                self._transition(task, StateEvent.WORKER_FAIL)
                continue

            # Materialize files into workspace for syntax check
            written = self._write_files(worker_out.files)

            # Syntax gate
            syn_result = check_syntax(written)
            if not syn_result.ok:
                # Try Codex escalation if L1 is exhausted and codex supports it
                if self.deps.budget.l1_exhausted(task_id) and hasattr(
                    self.deps.codex, "dispatch_escalation"
                ):
                    escalated_files = self.deps.codex.dispatch_escalation(
                        task_id, spec.spec_md, worker_out.files
                    )
                    self.deps.budget.record_codex_attempt(task_id)
                    task.codex_escalated = self.deps.budget.codex_attempts(task_id)

                    esc_path_result = check_paths(
                        produced=list(escalated_files.keys()),
                        whitelist=task.path_whitelist,
                    )
                    if esc_path_result.ok:
                        esc_written = self._write_files(escalated_files)
                        esc_syn_result = check_syntax(esc_written)
                        if esc_syn_result.ok:
                            worker_out = type(worker_out)(
                                task_id=worker_out.task_id,
                                files=escalated_files,
                                tokens_used=worker_out.tokens_used,
                            )
                            self._transition(task, StateEvent.WORKER_DONE)
                            review = self.deps.codex.review(
                                task_id, worker_out.files, spec.spec_md
                            )
                            self.deps.budget.record_tokens(task_id, review.tokens_used)
                            self.deps.md.write_review(task_id, review.review_md)
                            self._record(
                                task_id,
                                task.project_id,
                                "codex",
                                "orchestrator",
                                "review",
                                review.review_md,
                                tokens_out=review.tokens_used,
                            )
                            if not review.passed:
                                self._transition(task, StateEvent.REVIEW_FAIL)
                                continue
                            self._transition(task, StateEvent.REVIEW_PASS)

                            audit = self.deps.auditor.audit(task_id, worker_out.files)
                            self.deps.budget.record_tokens(task_id, audit.tokens_used)
                            self.deps.md.write_audit(task_id, audit.audit_md)
                            self._record(
                                task_id,
                                task.project_id,
                                "glm5",
                                "orchestrator",
                                "audit",
                                audit.audit_md,
                                tokens_out=audit.tokens_used,
                            )
                            if not audit.passed:
                                self._transition(task, StateEvent.AUDIT_FAIL)
                                continue
                            self._transition(task, StateEvent.AUDIT_PASS)
                            return

                    if self.deps.budget.l2_exhausted(task_id):
                        self._transition(task, StateEvent.ESCALATION_EXHAUSTED)
                        return
                    self._transition(task, StateEvent.WORKER_FAIL)
                    continue

                self._transition(task, StateEvent.WORKER_FAIL)
                continue

            self._transition(task, StateEvent.WORKER_DONE)

            # Codex review
            review = self.deps.codex.review(task_id, worker_out.files, spec.spec_md)
            self.deps.budget.record_tokens(task_id, review.tokens_used)
            self.deps.md.write_review(task_id, review.review_md)
            self._record(
                task_id,
                task.project_id,
                "codex",
                "orchestrator",
                "review",
                review.review_md,
                tokens_out=review.tokens_used,
            )
            if not review.passed:
                self._transition(task, StateEvent.REVIEW_FAIL)
                continue
            self._transition(task, StateEvent.REVIEW_PASS)

            # Audit
            audit = self.deps.auditor.audit(task_id, worker_out.files)
            self.deps.budget.record_tokens(task_id, audit.tokens_used)
            self.deps.md.write_audit(task_id, audit.audit_md)
            self._record(
                task_id,
                task.project_id,
                "glm5",
                "orchestrator",
                "audit",
                audit.audit_md,
                tokens_out=audit.tokens_used,
            )
            if not audit.passed:
                self._transition(task, StateEvent.AUDIT_FAIL)
                continue
            self._transition(task, StateEvent.AUDIT_PASS)
            return

    # ----- helpers -----

    def _write_files(self, files: dict[str, str]) -> list[Path]:
        written: list[Path] = []
        for rel, content in files.items():
            target = self.deps.project_source_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written.append(target)
        return written

    def _transition(self, task, event: StateEvent) -> None:
        new_status = next_state(task.status, event)
        task.status = new_status
        task.attempts = self.deps.budget.attempts(task.id)
        task.tokens_used = self.deps.budget.tokens(task.id)
        task.codex_escalated = self.deps.budget.codex_attempts(task.id)
        task.updated_at = datetime.now()
        self.deps.store.upsert_task(task)

    def _record(
        self,
        task_id: str,
        project_id: str,
        from_agent: str,
        to_agent: str,
        kind: str,
        content: str,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        self.deps.store.append_interaction(
            Interaction(
                project_id=project_id,
                task_id=task_id,
                from_agent=from_agent,
                to_agent=to_agent,
                kind=kind,
                content=content,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )
