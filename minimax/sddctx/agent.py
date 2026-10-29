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

"""Drive one development task from context to a verified code change.

The flow of a task is:

1. The specification, code and test material is imported into seekDB.
2. The task selects the applicable material and assembles a context.
3. The context is handed to MiniMax, which returns a unified diff.
4. The diff is applied to the business project.
5. The target tests and the regression tests are executed.
6. The state of the task is written into PowerContext and read back by a
   later run.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sddctx.minimax_client import MiniMaxResponse
from sddctx.retrieve import TaskContext
from sddctx.state import TaskState

#: Prompt that tells MiniMax how to answer.
SYSTEM_PROMPT = """\
You are a careful software engineer that implements a change from a written specification.

Rules:
- Answer with one unified diff and nothing else.
- Wrap the diff in a single fenced code block that starts with ```diff.
- Only change the files that the specification points at.
- Keep the existing code style, the license header and the public behaviour that the specification lists as unchanged.
- Never remove or weaken an existing test.
"""

#: Prompt template that carries the assembled context.
PROMPT_TEMPLATE = """\
Task:
{task}

Applicable specifications:
{specs}

Files that have to be changed:
{files}

Symbols that the specifications point at:
{code}

Tests that verify the specifications:
{tests}

Task state reused from an earlier run:
{state}

Implement the task. Return one unified diff that changes the code so that the
specifications are satisfied and the listed behaviour stays unchanged.

Rules for the diff:
- Use the exact line numbers and the exact context lines of the file above.
- Keep every line of the file that does not have to change unchanged, also
  the blank lines and the license header.
- Change only the files listed above.
"""


@dataclass
class TestRun:
    """Result of one test execution.

    Attributes:
        command: Command that was executed.
        exit_code: Exit code of the command.
        stdout: Captured standard output.
        duration_seconds: Wall clock duration of the run.
    """

    command: list[str]
    exit_code: int
    stdout: str
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable view of the run.

        Returns:
            The run as plain data.
        """
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "stdout": self.stdout,
        }


@dataclass
class TaskResult:
    """Outcome of one task run.

    Attributes:
        task_id: Identifier of the task.
        context: The context that was assembled.
        response: The answer MiniMax returned.
        diff: The unified diff of the change.
        changed_files: Files the diff changed.
        before: Content of the changed files before the change.
        after: Content of the changed files after the change.
        test_runs: Test executions of the run.
        state: The state that was written into PowerContext.
        artifacts: Files that the run produced.
    """

    task_id: str
    context: TaskContext
    response: MiniMaxResponse | None = None
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)
    test_runs: list[TestRun] = field(default_factory=list)
    state: TaskState | None = None
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable view of the result.

        Returns:
            The result as plain data.
        """
        return {
            "task_id": self.task_id,
            "context": self.context.to_dict(),
            "minimax": {
                "model": self.response.model,
                "input_tokens": self.response.input_tokens,
                "output_tokens": self.response.output_tokens,
                "answer": self.response.text,
            }
            if self.response
            else None,
            "diff": self.diff,
            "changed_files": list(self.changed_files),
            "before": dict(self.before),
            "after": dict(self.after),
            "test_runs": [run.to_dict() for run in self.test_runs],
            "state": self.state.to_dict() if self.state else None,
            "artifacts": list(self.artifacts),
        }


def _bullets(items: list[str]) -> str:
    """Render a list of lines as a Markdown list.

    Args:
        items: Lines to render.

    Returns:
        The rendered list, or a placeholder when it is empty.
    """
    if not items:
        return "(none)"
    return "\n".join(f"- {item}" for item in items)


def format_prompt(context: TaskContext) -> str:
    """Render the assembled context into the prompt of the model.

    Args:
        context: The assembled context.

    Returns:
        The prompt text.
    """
    specs = (
        "\n".join(
            f"[{spec.spec_id}] (version {spec.version}) {spec.title}\n"
            f"Source: {spec.source_file}:{spec.line_start}-{spec.line_end}\n"
            f"Requirement:\n{spec.body}\n"
            f"Acceptance criteria:\n{_bullets(spec.acceptance)}\n"
            f"Behaviour that must stay unchanged:\n{_bullets(spec.invariants)}"
            for spec in context.specs
        )
        or "(none matched)"
    )

    files = (
        "\n".join(f"### {entry['file_path']}\n```python\n{entry.get('content', '')}\n```" for entry in context.files)
        or "(none matched)"
    )

    code = (
        "\n".join(
            f"- {item['file_path']}:{item['line_start']}-{item['line_end']} {item['kind']} {item['name']}"
            for item in context.code
        )
        or "(none matched)"
    )

    tests = (
        "\n".join(
            f"- {item['file_path']}:{item['line_start']} {item['name']} (required by {item.get('required_by', '')})"
            for item in context.tests
        )
        or "(none matched)"
    )

    state = json.dumps(context.state, ensure_ascii=False, indent=2) if context.state else "(no state yet)"
    return PROMPT_TEMPLATE.format(
        task=context.task,
        specs=specs,
        files=files,
        code=code,
        tests=tests,
        state=state,
    )


def run_tests(project_dir: Path, python: str, target: list[str]) -> TestRun:
    """Execute a pytest selection inside the business project.

    Args:
        project_dir: Root of the business project.
        python: Interpreter that runs pytest.
        target: Test selection passed to pytest.

    Returns:
        The result of the run.
    """
    command = [python, "-m", "pytest", "-q", *target]
    started = datetime.now(UTC)
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    ended = datetime.now(UTC)
    return TestRun(
        command=command,
        exit_code=completed.returncode,
        stdout=(completed.stdout or "") + (completed.stderr or ""),
        duration_seconds=(ended - started).total_seconds(),
    )


def snapshot_files(project_dir: Path, paths: list[str]) -> dict[str, str]:
    """Read the current content of the given project files.

    Args:
        project_dir: Root of the business project.
        paths: Paths relative to the project root.

    Returns:
        The content of every file that exists.
    """
    content: dict[str, str] = {}
    for relative in paths:
        target = project_dir / relative
        if target.exists():
            content[relative] = target.read_text(encoding="utf-8")
    return content


def build_state(
    *,
    task_id: str,
    objective: str,
    scope_id: str,
    context: TaskContext,
    done: list[str],
    remaining: list[str],
    checks: list[dict[str, Any]],
    artifacts: list[str],
) -> TaskState:
    """Build the task state from the outcome of a run.

    Args:
        task_id: Identifier of the task.
        objective: What the task has to achieve.
        scope_id: PowerContext Scope that holds the state.
        context: The context that was assembled.
        done: Work that has been completed.
        remaining: Work that is still open.
        checks: Checks that were executed.
        artifacts: Artifacts that the run produced.

    Returns:
        The assembled state.
    """
    return TaskState(
        task_id=task_id,
        objective=objective,
        scope_id=scope_id,
        facts=[f"{spec.spec_id} applies to {spec.scope}" for spec in context.specs],
        in_scope=sorted({spec.scope for spec in context.specs if spec.scope}),
        exclusions=[f"{spec.spec_id}: {invariant}" for spec in context.specs for invariant in spec.invariants],
        completion_criteria=[
            *[f"{spec.spec_id}: {criterion}" for spec in context.specs for criterion in spec.acceptance],
            "The target tests of the specification pass.",
            "The regression tests of the project still pass.",
        ],
        done=done,
        remaining=remaining,
        checks=checks,
        artifacts=artifacts,
        updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
