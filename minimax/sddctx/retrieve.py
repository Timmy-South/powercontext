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

"""Select the engineering material that applies to a development task.

Selection uses two signals that both come from seekDB:

``full text``
    The identifier of the task is matched against the indexed text of the
    specification entries with ``MATCH ... AGAINST`` in boolean mode.

``scope``
    The specification declares the source path it applies to. The code
    symbols and the test cases stored for that path belong to the task.

The ranking therefore points at the specification entries that mention the
task and at the code and tests that those entries declare.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sddctx.store import SeekDBStore

#: Matches identifiers such as ``filter_orders`` or ``OrderCriteria``.
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

#: Matches runs of CJK characters.
_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

#: Words that carry no meaning for the selection.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "must",
        "should",
        "from",
        "into",
        "when",
        "not",
        "add",
        "new",
        "support",
    }
)


@dataclass
class SelectedSpec:
    """A specification entry selected for a task.

    Attributes:
        spec_id: Identifier of the specification.
        title: Title of the specification.
        body: Requirement text of the specification.
        scope: Source path the specification applies to.
        version: Revision number of the specification.
        source_file: File the specification was parsed from.
        line_start: First line of the specification in its file.
        line_end: Last line of the specification in its file.
        score: Relevance score produced by the selection.
        matched_by: Signals that selected the specification.
    """

    spec_id: str
    title: str
    body: str
    scope: str
    version: int
    source_file: str
    line_start: int
    line_end: int
    score: float = 0.0
    matched_by: list[str] = field(default_factory=list)


@dataclass
class TaskContext:
    """The development context assembled for a task.

    Attributes:
        task: The task description the context was built for.
        specs: Specification entries that apply to the task.
        code: Code symbols that the selected specifications point at.
        files: Complete content of the files the selected specifications point at.
        tests: Test cases that verify the selected specifications.
        state: Task state reused from a previous run.
    """

    task: str
    specs: list[SelectedSpec] = field(default_factory=list)
    code: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable view of the context.

        Returns:
            The context as plain data.
        """
        return {
            "task": self.task,
            "specs": [
                {
                    "spec_id": spec.spec_id,
                    "title": spec.title,
                    "version": spec.version,
                    "scope": spec.scope,
                    "source_file": spec.source_file,
                    "line_start": spec.line_start,
                    "line_end": spec.line_end,
                    "score": round(spec.score, 6),
                    "matched_by": spec.matched_by,
                    "requirement": spec.body,
                }
                for spec in self.specs
            ],
            "code": self.code,
            "files": self.files,
            "tests": self.tests,
            "state": self.state,
        }


def extract_query_terms(task: str) -> tuple[list[str], list[str]]:
    """Split a task description into index terms.

    Args:
        task: Task description.

    Returns:
        A tuple of ASCII identifiers and CJK phrases.
    """
    identifiers = [
        token.lower()
        for token in _IDENTIFIER_RE.findall(task)
        if token.lower() not in _STOPWORDS
    ]
    phrases = list(dict.fromkeys(_CJK_RE.findall(task)))
    return identifiers, phrases


def _identifier_query(identifiers: list[str]) -> str:
    """Build a boolean full text query from identifiers.

    Args:
        identifiers: Identifiers found in the task description.

    Returns:
        A boolean mode query string.
    """
    return " ".join(f"+{token}" for token in identifiers)


def select_specs(store: SeekDBStore, task: str, limit: int = 5) -> list[SelectedSpec]:
    """Select the specification entries that apply to a task.

    Args:
        store: Store holding the imported material.
        task: Task description.
        limit: Maximum number of specifications to return.

    Returns:
        Selected specifications ordered by descending relevance.
    """
    identifiers, phrases = extract_query_terms(task)
    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}

    if identifiers:
        query = _identifier_query(identifiers)
        rows = store.query(
            """
            SELECT spec_id, MATCH(search_text) AGAINST (%s IN BOOLEAN MODE) AS score
            FROM spec_items
            WHERE MATCH(search_text) AGAINST (%s IN BOOLEAN MODE)
            """,
            (query, query),
        )
        for spec_id, score in rows:
            scores[spec_id] = scores.get(spec_id, 0.0) + float(score)
            matched.setdefault(spec_id, []).append("fulltext")

    for phrase in phrases:
        rows = store.query(
            """
            SELECT spec_id, title, body
            FROM spec_items
            WHERE body LIKE %s OR title LIKE %s
            """,
            (f"%{phrase}%", f"%{phrase}%"),
        )
        for spec_id, _title, _body in rows:
            scores[spec_id] = scores.get(spec_id, 0.0) + 1.0
            matched.setdefault(spec_id, []).append(f"phrase:{phrase}")

    if not scores:
        return []

    selected: list[SelectedSpec] = []
    for spec_id, score in scores.items():
        record = store.spec_by_id(spec_id)
        if record is None:
            continue
        selected.append(
            SelectedSpec(
                spec_id=record["spec_id"],
                title=record["title"],
                body=record["body"],
                scope=record["scope"],
                version=int(record["version"]),
                source_file=record["source_file"],
                line_start=int(record["line_start"]),
                line_end=int(record["line_end"]),
                score=score,
                matched_by=sorted(set(matched.get(spec_id, []))),
            )
        )
    selected.sort(key=lambda spec: (-spec.score, spec.spec_id))
    return selected[:limit]


def build_context(
    store: SeekDBStore,
    task: str,
    *,
    limit: int = 5,
    state: dict[str, Any] | None = None,
    project_dir: Path | None = None,
) -> TaskContext:
    """Assemble the development context of a task.

    The specification entries are selected first. Their declared scope then
    decides which code symbols, which files and which test cases belong to
    the task.

    Args:
        store: Store holding the imported material.
        task: Task description.
        limit: Maximum number of specifications to select.
        state: Task state reused from a previous run.
        project_dir: Root of the business project. When it is given, the
            complete content of every selected file is read, so that the
            model receives the file it has to change as it is.

    Returns:
        The assembled context.
    """
    specs = select_specs(store, task, limit=limit)

    code: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    seen_code: set[str] = set()
    seen_files: set[str] = set()
    seen_tests: set[str] = set()
    for spec in specs:
        if not spec.scope:
            continue
        for symbol in store.symbols_in_scope(spec.scope):
            if symbol["symbol_id"] in seen_code:
                continue
            seen_code.add(symbol["symbol_id"])
            code.append({**symbol, "required_by": spec.spec_id})
        if spec.scope not in seen_files:
            seen_files.add(spec.scope)
            files.append({"file_path": spec.scope, "required_by": spec.spec_id})
        for test in store.tests_in_scope(spec.scope):
            if test["test_id"] in seen_tests:
                continue
            seen_tests.add(test["test_id"])
            tests.append({**test, "required_by": spec.spec_id})

    if project_dir is not None:
        for entry in files:
            target = Path(project_dir) / entry["file_path"]
            entry["content"] = target.read_text(encoding="utf-8") if target.exists() else ""
            entry["line_count"] = len(entry["content"].splitlines())

    return TaskContext(
        task=task,
        specs=specs,
        code=code,
        files=files,
        tests=tests,
        state=dict(state or {}),
    )
