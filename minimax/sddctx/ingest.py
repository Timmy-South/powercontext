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

"""Import specifications, code symbols and tests into the seekDB store.

A specification document starts with a heading that carries the specification
identifier, for example ``# SPEC-FILTER-003 客户等级分组筛选``. The body is
split into the sections the context module understands:

``## 需求``
    The requirement text, which is what the code change has to satisfy.

``## 适用范围``
    The source paths the specification applies to.

``## 验收``
    The acceptance criteria.

``## 保持不变``
    The behaviour that must survive the change.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sddctx.store import SeekDBStore

#: Matches the specification identifier inside a document heading.
_SPEC_ID_RE = re.compile(r"^#\s+(SPEC-[A-Z0-9]+-\d+)\s*(.*)$")

#: Matches a Markdown level two heading.
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")

#: Matches a Markdown bullet used to list scope paths.
_SCOPE_PATH_RE = re.compile(r"`([^`]+)`")


@dataclass
class ParsedSpec:
    """One specification entry parsed from a Markdown document.

    Attributes:
        spec_id: Identifier taken from the document heading.
        title: Remaining text of the document heading.
        requirement: Requirement body of the specification.
        acceptance: Acceptance criteria lines.
        invariants: Behaviour that must not change.
        scopes: Source paths the specification applies to.
        source_file: Absolute path of the source document.
        line_start: First line of the specification in its file.
        line_end: Last line of the specification in its file.
    """

    spec_id: str
    title: str
    requirement: str
    acceptance: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    source_file: str = ""
    line_start: int = 0
    line_end: int = 0

    @property
    def body(self) -> str:
        """Return the requirement text of the specification."""
        return self.requirement


def _section_key(title: str) -> str:
    """Normalise a section heading into a lookup key.

    Args:
        title: Raw heading text.

    Returns:
        Lowercase key without surrounding whitespace.
    """
    return title.strip().lower()


def parse_spec_file(path: Path) -> ParsedSpec | None:
    """Parse one specification document.

    Args:
        path: Path of the Markdown document.

    Returns:
        The parsed specification, or ``None`` when the heading carries no
        specification identifier.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    heading_index = -1
    spec_id = ""
    title = ""
    for index, line in enumerate(lines):
        match = _SPEC_ID_RE.match(line)
        if match:
            heading_index = index
            spec_id = match.group(1)
            title = match.group(2).strip()
            break
    if heading_index < 0:
        return None

    sections: dict[str, list[str]] = {}
    current = ""
    for line in lines[heading_index + 1 :]:
        section_match = _SECTION_RE.match(line)
        if section_match:
            current = _section_key(section_match.group(1))
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)

    def joined(key: str) -> str:
        return "\n".join(sections.get(key, [])).strip()

    def items(key: str) -> list[str]:
        collected: list[str] = []
        for line in sections.get(key, []):
            text = line.strip()
            if not text:
                continue
            collected.append(text[2:].strip() if text.startswith("- ") else text)
        return collected

    requirement = joined("需求")
    acceptance = items("验收")
    invariants = items("保持不变")

    scopes: list[str] = []
    for line in sections.get("适用范围", []):
        scopes.extend(_SCOPE_PATH_RE.findall(line))

    return ParsedSpec(
        spec_id=spec_id,
        title=title,
        requirement=requirement,
        acceptance=acceptance,
        invariants=invariants,
        scopes=scopes,
        source_file=str(path),
        line_start=heading_index + 1,
        line_end=len(lines),
    )


def build_search_text(spec: ParsedSpec) -> str:
    """Build the text that the full text index of seekDB searches.

    The identifier, the title and the requirement are repeated so that both
    the machine readable identifier and the natural language requirement
    match a query.

    Args:
        spec: Specification to index.

    Returns:
        Indexed text.
    """
    parts = [spec.spec_id, spec.title, spec.requirement]
    parts.extend(spec.acceptance)
    parts.extend(spec.invariants)
    parts.extend(spec.scopes)
    return " \n".join(part for part in parts if part)


def collect_symbols(project_dir: Path) -> list[dict[str, Any]]:
    """Extract the top level symbols of every Python file of a project.

    Args:
        project_dir: Root of the business project.

    Returns:
        Symbol records for functions and classes.
    """
    symbols: list[dict[str, Any]] = []
    for file_path in sorted(project_dir.rglob("*.py")):
        if ".venv" in file_path.parts or "site-packages" in file_path.parts:
            continue
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        relative = file_path.relative_to(project_dir).as_posix()
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            start = node.lineno
            end = getattr(node, "end_lineno", start) or start
            snippet = "\n".join(lines[start - 1 : end])
            symbols.append(
                {
                    "symbol_id": f"{relative}::{node.name}",
                    "file_path": relative,
                    "name": node.name,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "line_start": start,
                    "line_end": end,
                    "snippet": snippet,
                }
            )
    return symbols


def collect_tests(project_dir: Path, symbol_names: list[str]) -> list[dict[str, Any]]:
    """Extract the test functions of every test file of a project.

    Each test records the names of the project symbols that its body refers
    to. That relation lets the context module decide which tests verify which
    specification.

    Args:
        project_dir: Root of the business project.
        symbol_names: Names of the symbols defined by the project.

    Returns:
        Test records.
    """
    tests: list[dict[str, Any]] = []
    for file_path in sorted(project_dir.rglob("test_*.py")):
        if ".venv" in file_path.parts or "site-packages" in file_path.parts:
            continue
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            continue
        relative = file_path.relative_to(project_dir).as_posix()
        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                start = node.lineno
                end = getattr(node, "end_lineno", start) or start
                body = "\n".join(lines[start - 1 : end])
                referenced = [name for name in symbol_names if re.search(rf"\b{re.escape(name)}\b", body)]
                tests.append(
                    {
                        "test_id": f"{relative}::{node.name}",
                        "file_path": relative,
                        "name": node.name,
                        "line_start": node.lineno,
                        "symbol_refs": referenced,
                    }
                )
    return tests


def import_materials(
    store: SeekDBStore,
    *,
    specs_dir: Path,
    project_dir: Path,
) -> dict[str, Any]:
    """Import all material of a project into the store.

    Args:
        store: Store that receives the material.
        specs_dir: Directory holding the specification documents.
        project_dir: Root of the business project.

    Returns:
        Summary of the import, including the specifications that changed.
    """
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    specs: list[ParsedSpec] = []
    for path in sorted(specs_dir.glob("*.md")):
        parsed = parse_spec_file(path)
        if parsed is not None:
            specs.append(parsed)

    root = specs_dir.parent
    changed: list[str] = []
    for spec in specs:
        content_hash = hashlib.sha256(spec.requirement.encode("utf-8")).hexdigest()
        existing = store.spec_by_id(spec.spec_id)
        version = 1
        if existing is not None:
            version = int(existing["version"]) + (1 if existing["content_hash"] != content_hash else 0)
            version = max(version, 1)
        try:
            source_file = Path(spec.source_file).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            source_file = spec.source_file
        was_changed = store.upsert_spec(
            spec_id=spec.spec_id,
            title=spec.title,
            body=spec.requirement,
            search_text=build_search_text(spec),
            scope=spec.scopes[0] if spec.scopes else "",
            version=version,
            source_file=source_file,
            line_start=spec.line_start,
            line_end=spec.line_end,
            content_hash=content_hash,
            updated_at=started_at,
        )
        if was_changed:
            changed.append(spec.spec_id)

    symbols = collect_symbols(project_dir)
    symbol_names = sorted({symbol["name"] for symbol in symbols})
    tests = collect_tests(project_dir, symbol_names)
    store.replace_code_symbols(symbols)
    store.replace_test_cases(tests)

    run_id = hashlib.sha256(f"{started_at}|{len(specs)}".encode()).hexdigest()[:16]
    store.record_import_run(run_id, started_at, len(specs), len(symbols), len(tests))

    return {
        "run_id": run_id,
        "started_at": started_at,
        "spec_count": len(specs),
        "code_symbol_count": len(symbols),
        "test_count": len(tests),
        "changed_specs": changed,
        "specs": [spec.spec_id for spec in specs],
    }
