# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Task state storage backed by a PowerContext Server.

The state of a development task is written into a PowerContext Scope as
durable Sources:

``work-contract``
    The objective of the task, the facts it was given, what is in scope and
    what has to stay untouched.

``task-outcome``
    The observations of the run, the checks that were executed, the artifacts
    that were produced and the work that is still open.

The same information is additionally stored as Atomic Memory so that a later
run can recall it with a search. Because the state lives in the Server and
not in the module process, a module that is restarted reads the state back
from the Server.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: Source type used for the work contract of a task.
CONTRACT_SOURCE = "sddctx-contract"

#: Source type used for the outcome of a task.
OUTCOME_SOURCE = "sddctx-outcome"


def _as_dict(content: Any) -> dict[str, Any]:
    """Return the content of a Source as a dictionary.

    A Source holds either an already decoded object or the JSON text of that
    object.

    Args:
        content: Content of the Source.

    Returns:
        The content as a dictionary, empty when it holds no object.
    """
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _check_status(check: dict[str, Any]) -> str:
    """Map a recorded check onto the status vocabulary of PowerContext.

    Args:
        check: Check that was executed.

    Returns:
        One of ``passed``, ``failed``, ``skipped``, ``timed_out``,
        ``unavailable``, ``cancelled`` or ``unknown``.
    """
    if check.get("passed") is True:
        return "passed"
    if check.get("passed") is False:
        return "failed"
    status = str(check.get("status", "")).lower()
    if status in {"passed", "failed", "skipped", "timed_out", "unavailable", "cancelled", "unknown"}:
        return status
    exit_code = check.get("exit_code")
    if isinstance(exit_code, int):
        return "passed" if exit_code == 0 else "failed"
    return "unknown"


@dataclass
class TaskState:
    """State of a development task.

    Attributes:
        task_id: Identifier of the task.
        objective: What the task has to achieve.
        scope_id: PowerContext Scope that holds the state.
        facts: Facts the task was given.
        in_scope: Paths the task may change.
        exclusions: Paths the task must not change.
        completion_criteria: Conditions that mark the task as done.
        done: Work that has been completed.
        remaining: Work that is still open.
        checks: Checks that were executed, with their result.
        artifacts: Artifacts that the run produced.
        updated_at: Timestamp of the last write.
        source_ids: Ids of the Sources that hold the state.
    """

    task_id: str
    objective: str = ""
    scope_id: str = ""
    facts: list[str] = field(default_factory=list)
    in_scope: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    updated_at: str = ""
    source_ids: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable view of the state.

        Returns:
            The state as plain data.
        """
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "scope_id": self.scope_id,
            "facts": list(self.facts),
            "in_scope": list(self.in_scope),
            "exclusions": list(self.exclusions),
            "completion_criteria": list(self.completion_criteria),
            "done": list(self.done),
            "remaining": list(self.remaining),
            "checks": list(self.checks),
            "artifacts": list(self.artifacts),
            "updated_at": self.updated_at,
            "source_ids": dict(self.source_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskState:
        """Rebuild a state from its plain data view.

        Args:
            data: State data.

        Returns:
            The reconstructed state.
        """
        return cls(
            task_id=str(data.get("task_id", "")),
            objective=str(data.get("objective", "")),
            scope_id=str(data.get("scope_id", "")),
            facts=list(data.get("facts", [])),
            in_scope=list(data.get("in_scope", [])),
            exclusions=list(data.get("exclusions", [])),
            completion_criteria=list(data.get("completion_criteria", [])),
            done=list(data.get("done", [])),
            remaining=list(data.get("remaining", [])),
            checks=list(data.get("checks", [])),
            artifacts=list(data.get("artifacts", [])),
            updated_at=str(data.get("updated_at", "")),
            source_ids=dict(data.get("source_ids", {})),
        )


class PowerContextClient:
    """Small HTTP client for the PowerContext Server."""

    def __init__(
        self,
        *,
        base_url: str,
        scope_id: str,
        token: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Configure the client.

        Args:
            base_url: Base URL of the Server.
            scope_id: Logical name of the Scope. It is used as the
                idempotency key, so the same name always resolves to the
                same Scope, also after the module was restarted.
            token: Optional bearer token.
            timeout: Per-request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.scope_id = scope_id
        self.token = token
        self.timeout = timeout
        self._resolved_scope_id: str | None = None

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """Run one HTTP request against the Server.

        Args:
            method: HTTP method.
            path: Path of the endpoint.
            body: Optional JSON body.

        Returns:
            The decoded response.

        Raises:
            RuntimeError: When the Server responds with an error status.
        """
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"PowerContext {method} {path} failed with HTTP {error.code}: {detail[:400]}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"PowerContext {method} {path} failed: {error.reason}") from error

    # ------------------------------------------------------------------
    # Scope handling
    # ------------------------------------------------------------------

    def ensure_scope(self, title: str = "MiniMax SDD Context") -> str:
        """Resolve the configured Scope and return its id.

        The configured name is used as the idempotency key of the Scope, so
        repeated calls and calls from a restarted module always resolve to
        the same Scope.

        Args:
            title: Title used when the Scope has to be created.

        Returns:
            The Scope id assigned by the Server.
        """
        if self._resolved_scope_id is not None:
            return self._resolved_scope_id
        listing = self._request("GET", "/v1/scopes")
        for item in listing.get("items", []):
            if item.get("title") == title:
                self._resolved_scope_id = str(item["scope_id"])
                return self._resolved_scope_id
        created = self._request(
            "POST",
            "/v1/scopes",
            {
                "title": title,
                "summary": "Task state of the MiniMax SDD context module.",
                "idempotency_key": self.scope_id,
            },
        )
        self._resolved_scope_id = str(created["scope_id"])
        return self._resolved_scope_id

    @property
    def resolved_scope_id(self) -> str:
        """Return the Scope id, resolving it when needed."""
        return self._resolved_scope_id or self.ensure_scope()

    # ------------------------------------------------------------------
    # State writes
    # ------------------------------------------------------------------

    def save_contract(self, state: TaskState) -> str:
        """Write the work contract of a task.

        Args:
            state: State that carries the contract.

        Returns:
            The Source id that holds the contract.
        """
        source_id = f"{CONTRACT_SOURCE}:{state.task_id}"
        contract = {
            "schema": "powercontext.work-contract.v1",
            "trust": "untrusted_input",
            "objective": state.objective,
            "facts": [{"text": fact, "basis": "declared", "evidence": []} for fact in state.facts],
            "in_scope": list(state.in_scope),
            "exclusions": list(state.exclusions),
            "completion_criteria": list(state.completion_criteria),
            "authorization_notes": [],
            "open_questions": [],
        }
        self._request(
            "POST",
            "/v1/work/contracts/create",
            {"scope_id": self.resolved_scope_id, "source_id": source_id, "contract": contract},
        )
        state.source_ids["contract"] = source_id
        return source_id

    def save_outcome(self, state: TaskState) -> str:
        """Write the outcome of a task.

        Args:
            state: State that carries the outcome.

        Returns:
            The Source id that holds the outcome.
        """
        source_id = f"{OUTCOME_SOURCE}:{state.task_id}"
        outcome = {
            "schema": "powercontext.task-outcome.v1",
            "trust": "untrusted_observation",
            "objective": state.objective,
            "status": "succeeded" if not state.remaining else "partial",
            "summary": f"{len(state.done)} items done, {len(state.remaining)} items remaining.",
            "observations": [{"text": item, "basis": "declared", "evidence": []} for item in state.done],
            "checks": [
                {
                    "name": str(check.get("name", check.get("command", "check"))),
                    "status": _check_status(check),
                    "details": str(check.get("details", check.get("command", ""))),
                    "basis": "declared",
                    "evidence": [],
                }
                for check in state.checks
            ],
            "produced_artifacts": [],
            "remaining_work": list(state.remaining),
        }
        self._request(
            "POST",
            "/v1/work/outcomes/record",
            {"scope_id": self.resolved_scope_id, "source_id": source_id, "outcome": outcome},
        )
        state.source_ids["outcome"] = source_id
        return source_id

    def remember(self, state: TaskState, text: str) -> None:
        """Store one summary of the task as Atomic Memory.

        Args:
            state: State the summary belongs to.
            text: Text of the summary.
        """
        self._request(
            "POST",
            "/v1/memory/remember",
            {"scope_id": self.resolved_scope_id, "kind": "decision", "text": text},
        )

    # ------------------------------------------------------------------
    # State reads
    # ------------------------------------------------------------------

    def read_state(self, task_id: str) -> TaskState | None:
        """Read the state of a task back from the Server.

        Args:
            task_id: Identifier of the task.

        Returns:
            The state, or ``None`` when the Server holds no state for it.
        """
        listing = self._request("GET", f"/v1/scopes/{self.resolved_scope_id}/sources")
        contract_id = f"{CONTRACT_SOURCE}:{task_id}"
        outcome_id = f"{OUTCOME_SOURCE}:{task_id}"
        found: dict[str, Any] = {}
        for item in listing.get("items", []):
            source_id = item.get("source_id", "")
            if source_id == contract_id:
                found["contract"] = item
            elif source_id == outcome_id:
                found["outcome"] = item
        if not found:
            return None

        state = TaskState(task_id=task_id, scope_id=self.resolved_scope_id)
        contract = found.get("contract")
        if contract is not None:
            content = _as_dict(contract.get("content"))
            if content:
                state.objective = str(content.get("objective", ""))
                state.facts = [
                    str(claim.get("text", "")) for claim in content.get("facts", []) if isinstance(claim, dict)
                ]
                state.in_scope = list(content.get("in_scope", []))
                state.exclusions = list(content.get("exclusions", []))
                state.completion_criteria = list(content.get("completion_criteria", []))
            state.source_ids["contract"] = contract_id

        outcome = found.get("outcome")
        if outcome is not None:
            content = _as_dict(outcome.get("content"))
            if content:
                state.objective = state.objective or str(content.get("objective", ""))
                state.done = [
                    str(claim.get("text", "")) for claim in content.get("observations", []) if isinstance(claim, dict)
                ]
                state.checks = [
                    {
                        "name": str(check.get("name", "")),
                        "status": str(check.get("status", "")),
                        "details": str(check.get("details", "")),
                        "passed": check.get("status") == "passed",
                    }
                    for check in content.get("checks", [])
                    if isinstance(check, dict)
                ]
                state.artifacts = list(content.get("produced_artifacts", []))
                state.remaining = list(content.get("remaining_work", []))
            state.source_ids["outcome"] = outcome_id

        state.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        return state

    def search_memory(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the Atomic Memory of the Scope.

        Args:
            query: Search query.
            limit: Maximum number of hits.

        Returns:
            The memory hits.
        """
        result = self._request(
            "POST",
            "/v1/memory/search",
            {"scope_id": self.resolved_scope_id, "query": query, "limit": limit},
        )
        return list(result.get("hits", []))
