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

"""Run the verification sample of the SDD context module.

The script drives the whole flow and writes every artefact into
``artifacts/``:

1. import the material into the embedded seekDB instance,
2. assemble the development context of the task,
3. run the target tests and the regression tests before the change,
4. let MiniMax produce the change and apply it,
5. run the same tests again,
6. read the task state back from PowerContext.

Every step prints the command it ran and the exit code it produced, so the
log of the run can be checked against the delivered source.

Usage:
    python verify/run_verification.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "artifacts"
LOGS = ARTIFACTS / "logs"

#: The development task of the verification sample.
TASK = "为订单筛选增加客户等级分组过滤：customer_tiers 中的 premium 分组必须展开为 gold 与 silver"

#: Identifier of the task.
TASK_ID = "task-filter-003"

#: Test selection that carries the target behaviour.
TARGET_TESTS = ["tests/test_filters_tier_groups.py"]

#: Test selection that carries the behaviour that has to survive.
REGRESSION_TESTS = ["tests/test_filters_regression.py", "tests/test_pricing.py"]


def banner(title: str) -> None:
    """Print a step header.

    Args:
        title: Title of the step.
    """
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def run(command: list[str], cwd: Path, log_name: str | None = None) -> int:
    """Run a command and report its exit code.

    Args:
        command: Command to run.
        cwd: Working directory of the command.
        log_name: Name of the log file that captures the output.

    Returns:
        Exit code of the command.
    """
    printable = " ".join(command)
    print(f"$ {printable}")
    print(f"  cwd: {cwd}")
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing if existing else "")
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    print(f"  exit code: {completed.returncode}")
    if log_name:
        LOGS.mkdir(parents=True, exist_ok=True)
        header = f"$ {printable}\n# cwd: {cwd}\n# exit code: {completed.returncode}\n\n"
        (LOGS / log_name).write_text(header + output, encoding="utf-8")
        print(f"  log: {log_name}")
    tail = "\n".join(output.strip().splitlines()[-6:])
    if tail:
        print("  output tail:")
        for line in tail.splitlines():
            print(f"    {line}")
    return completed.returncode


def module_python() -> str:
    """Return the interpreter that runs the module.

    Returns:
        Path of the interpreter.
    """
    return sys.executable


def project_python() -> str:
    """Return the interpreter of the business project.

    Returns:
        Path of the interpreter.
    """
    venv = ROOT / "demo_shop" / ".venv"
    if os.name == "nt":
        candidate = venv / "Scripts" / "python.exe"
    else:
        candidate = venv / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def main() -> int:
    """Run the verification sample.

    Returns:
        Process exit code.
    """
    python = module_python()
    project = ROOT / "demo_shop"

    banner("Step 0 - restore the code to its state before the change")
    if run([python, str(ROOT / "verify" / "reset_code.py")], ROOT, "00-reset-code.log") != 0:
        print("FAIL: the code could not be restored")
        return 1

    banner("Step 1 - import the material into seekDB")
    if run([python, "-m", "sddctx", "import"], ROOT, "01-import.log") != 0:
        print("FAIL: the import failed")
        return 1

    banner("Step 2 - assemble the development context")
    context_json = ARTIFACTS / "context.json"
    run(
        [
            python,
            "-m",
            "sddctx",
            "context",
            "--task",
            TASK,
            "--task-id",
            TASK_ID,
            "--json",
            "--output",
            str(context_json),
        ],
        ROOT,
        "02-context.log",
    )
    context = json.loads(context_json.read_text(encoding="utf-8"))
    print(f"  specifications: {[spec['spec_id'] for spec in context['specs']]}")
    print(f"  code symbols:   {len(context['code'])}")
    print(f"  tests:          {len(context['tests'])}")
    version_before = next(
        (spec["version"] for spec in context["specs"] if spec["spec_id"] == "SPEC-FILTER-003"),
        0,
    )
    for spec in context["specs"]:
        print(f"  - {spec['spec_id']} v{spec['version']} <- {spec['source_file']}:{spec['line_start']}")

    banner("Step 3 - run the tests before the change")
    before_target = run(
        [project_python(), "-m", "pytest", "-v", *TARGET_TESTS],
        project,
        "03-before-target-tests.log",
    )
    before_regression = run(
        [project_python(), "-m", "pytest", "-v", *REGRESSION_TESTS],
        project,
        "04-before-regression-tests.log",
    )
    print(f"  target tests exit code before the change: {before_target} (expected non zero)")
    print(f"  regression tests exit code before the change: {before_regression} (expected zero)")

    banner("Step 4 - let MiniMax change the code and apply the change")
    apply_exit = run(
        [
            python,
            "-m",
            "sddctx",
            "apply",
            "--task",
            TASK,
            "--task-id",
            TASK_ID,
            "--project",
            str(project),
            "--python",
            project_python(),
            "--tests",
            *TARGET_TESTS,
            "--record",
            str(ARTIFACTS / "minimax-record.json"),
            "--diff-output",
            str(ARTIFACTS / "applied.patch"),
            "--prompt-output",
            str(ARTIFACTS / "minimax-prompt.txt"),
        ],
        ROOT,
        "05-apply.log",
    )
    print(f"  apply exit code: {apply_exit}")

    banner("Step 5 - run the same tests after the change")
    after_target = run(
        [project_python(), "-m", "pytest", "-v", *TARGET_TESTS],
        project,
        "06-after-target-tests.log",
    )
    after_regression = run(
        [project_python(), "-m", "pytest", "-v", *REGRESSION_TESTS],
        project,
        "07-after-regression-tests.log",
    )
    print(f"  target tests exit code after the change: {after_target} (expected zero)")
    print(f"  regression tests exit code after the change: {after_regression} (expected zero)")

    after_snapshot = ARTIFACTS / "code-snapshot-after" / "src" / "shop" / "filters.py"
    after_snapshot.parent.mkdir(parents=True, exist_ok=True)
    after_snapshot.write_text(
        (project / "src" / "shop" / "filters.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    print(f"  code snapshot after the change: {after_snapshot}")

    banner("Step 6 - read the task state back from PowerContext")
    run(
        [python, "-m", "sddctx", "state", "show", "--task-id", TASK_ID],
        ROOT,
        "08-state-show.log",
    )

    banner("Step 7 - restart the module and reuse the state in a new context")
    reused_context_json = ARTIFACTS / "context-reused-state.json"
    run(
        [
            python,
            "-m",
            "sddctx",
            "context",
            "--task",
            TASK,
            "--task-id",
            TASK_ID,
            "--json",
            "--output",
            str(reused_context_json),
        ],
        ROOT,
        "09-context-reused-state.log",
    )
    reused = json.loads(reused_context_json.read_text(encoding="utf-8"))
    reused_state = reused.get("state", {})
    print(f"  reused state objective: {reused_state.get('objective', '')}")
    print(f"  reused done items:      {reused_state.get('done', [])}")
    print(f"  reused remaining items: {reused_state.get('remaining', [])}")
    print(f"  reused checks:          {reused_state.get('checks', [])}")

    banner("Step 8 - update the specification, re-import and use the updated content")
    spec_update = run(
        [python, str(ROOT / "verify" / "apply_spec_update.py"), "--apply"],
        ROOT,
        "10-spec-update.log",
    )
    reimport = run([python, "-m", "sddctx", "import"], ROOT, "10b-spec-update-reimport.log")
    updated_context_json = ARTIFACTS / "context-after-spec-update.json"
    run(
        [
            python,
            "-m",
            "sddctx",
            "context",
            "--task",
            TASK,
            "--task-id",
            TASK_ID,
            "--json",
            "--output",
            str(updated_context_json),
        ],
        ROOT,
        "11-context-after-spec-update.log",
    )
    updated = json.loads(updated_context_json.read_text(encoding="utf-8"))
    updated_spec = next(
        (spec for spec in updated["specs"] if spec["spec_id"] == "SPEC-FILTER-003"),
        {},
    )
    print(f"  specification version before the update: {version_before}")
    print(f"  updated specification version: {updated_spec.get('version')}")
    print(f"  updated requirement mentions 'standard' group: {'standard' in updated_spec.get('requirement', '')}")
    spec_update_ok = (
        spec_update == 0
        and reimport == 0
        and int(updated_spec.get("version", 0)) > version_before
        and "`standard`" in updated_spec.get("requirement", "")
    )
    print(f"  the context uses the updated specification: {spec_update_ok}")
    run(
        [python, str(ROOT / "verify" / "apply_spec_update.py"), "--reset"],
        ROOT,
        "12-spec-update-reset.log",
    )
    run([python, "-m", "sddctx", "import"], ROOT, "12b-spec-update-reset-reimport.log")

    banner("Step 9 - record the database queries and the PowerContext state")
    run(
        [python, str(ROOT / "verify" / "record_usage.py")],
        ROOT,
        "13-usage-record.log",
    )

    banner("Summary")
    checks = {
        "target tests fail before the change": before_target != 0,
        "regression tests pass before the change": before_regression == 0,
        "target tests pass after the change": after_target == 0,
        "regression tests pass after the change": after_regression == 0,
        "the change was applied": apply_exit == 0,
        "the task state was read back from PowerContext": bool(reused_state.get("done")),
        "the context uses the updated specification": spec_update_ok,
    }
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
