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

"""Command line entry point of the SDD context module.

Commands:

``import``
    Import the specifications, the code symbols and the tests into seekDB.

``context``
    Assemble the development context of a task and print it.

``apply``
    Ask MiniMax for a change, apply it and run the tests.

``state save`` / ``state show``
    Write the state of a task into PowerContext and read it back.

``run``
    Run the whole flow of a task and write the technical record.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sddctx.agent import SYSTEM_PROMPT, TaskResult, build_state, format_prompt, run_tests, snapshot_files
from sddctx.config import Settings, load_settings
from sddctx.ingest import import_materials
from sddctx.minimax_client import MiniMaxClient
from sddctx.patch import apply_unified_diff, extract_diff
from sddctx.retrieve import build_context
from sddctx.state import PowerContextClient, TaskState
from sddctx.store import SeekDBStore

#: Test selections used when the caller does not name any.
DEFAULT_TEST_SELECTIONS = ("tests/test_filters_tier_groups.py",)


def _print(data: Any) -> None:
    """Print a JSON document.

    Args:
        data: The document to print.
    """
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _powercontext(settings: Settings) -> PowerContextClient:
    """Build a PowerContext client for the configured Server.

    Args:
        settings: Runtime settings.

    Returns:
        The client.
    """
    return PowerContextClient(
        base_url=settings.powercontext_url,
        scope_id=settings.scope_id,
        token=settings.powercontext_token,
    )


def command_import(settings: Settings, args: argparse.Namespace) -> int:
    """Import the project material into seekDB.

    Args:
        settings: Runtime settings.
        args: Parsed command line arguments.

    Returns:
        Process exit code.
    """
    specs_dir = Path(args.specs) if args.specs else settings.specs_dir
    project_dir = Path(args.project) if args.project else settings.project_dir
    for label, directory in (("specification directory", specs_dir), ("business project", project_dir)):
        if not directory.is_dir():
            print(f"error: the {label} does not exist: {directory}", file=sys.stderr)
            print(
                "set SDDCTX_ROOT to the directory that holds specs/ and demo_shop/, or pass --specs and --project",
                file=sys.stderr,
            )
            return 7

    with SeekDBStore(settings.db_dir) as store:
        summary = import_materials(store, specs_dir=specs_dir, project_dir=project_dir)
    if not summary["spec_count"]:
        print(f"error: no specification was found in {specs_dir}", file=sys.stderr)
        return 8
    _print(summary)
    return 0


def command_context(settings: Settings, args: argparse.Namespace) -> int:
    """Assemble and print the development context of a task.

    Args:
        settings: Runtime settings.
        args: Parsed command line arguments.

    Returns:
        Process exit code.
    """
    client = _powercontext(settings)
    state = None
    if not args.no_state:
        try:
            client.ensure_scope()
            state = client.read_state(args.task_id)
        except RuntimeError as error:
            print(f"warning: the task state could not be read: {error}", file=sys.stderr)

    project_dir = Path(args.project) if getattr(args, "project", None) else settings.project_dir
    with SeekDBStore(settings.db_dir) as store:
        context = build_context(
            store,
            args.task,
            limit=args.limit,
            state=state.to_dict() if state else {},
            project_dir=project_dir,
        )
    if args.output:
        Path(args.output).write_text(
            json.dumps(context.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.json:
        _print(context.to_dict())
    else:
        print(f"Task: {context.task}")
        print(f"Specifications ({len(context.specs)}):")
        for spec in context.specs:
            print(
                f"  - {spec.spec_id} v{spec.version} {spec.title} "
                f"[{spec.source_file}:{spec.line_start}] score={spec.score:.4f} via {', '.join(spec.matched_by)}"
            )
            print(f"      scope: {spec.scope}")
            for line in spec.body.splitlines():
                print(f"      | {line}")
        print(f"Code ({len(context.code)}):")
        for item in context.code:
            print(f"  - {item['file_path']}:{item['line_start']}-{item['line_end']} {item['kind']} {item['name']}")
        print(f"Tests ({len(context.tests)}):")
        for item in context.tests:
            print(f"  - {item['file_path']}:{item['line_start']} {item['name']}")
        if context.state:
            print("Reused state:")
            print(f"  objective: {context.state.get('objective', '')}")
            for item in context.state.get("done", []):
                print(f"  done: {item}")
            for item in context.state.get("remaining", []):
                print(f"  remaining: {item}")
            for check in context.state.get("checks", []):
                print(f"  check: {check}")
    if not context.specs:
        print("error: no specification matched the task", file=sys.stderr)
        print(
            "run 'python -m sddctx import' and check that the task names the identifiers of the specification",
            file=sys.stderr,
        )
        return 2
    return 0


def command_apply(settings: Settings, args: argparse.Namespace) -> int:
    """Ask MiniMax for a change, apply it and run the tests.

    Args:
        settings: Runtime settings.
        args: Parsed command line arguments.

    Returns:
        Process exit code.
    """
    client = _powercontext(settings)
    state: TaskState | None = None
    try:
        client.ensure_scope()
        state = client.read_state(args.task_id)
    except RuntimeError as error:
        print(f"warning: the task state could not be read: {error}", file=sys.stderr)

    project_dir = Path(args.project) if args.project else settings.project_dir
    with SeekDBStore(settings.db_dir) as store:
        context = build_context(
            store,
            args.task,
            limit=args.limit,
            state=state.to_dict() if state else {},
            project_dir=project_dir,
        )

    if not context.specs:
        print("error: no specification matched the task", file=sys.stderr)
        return 2

    minimax = MiniMaxClient(
        base_url=settings.minimax_base_url,
        model=settings.minimax_model,
        api_key=settings.minimax_api_key,
        timeout=settings.minimax_timeout,
    )
    prompt = format_prompt(context)
    if args.prompt_output:
        Path(args.prompt_output).write_text(prompt, encoding="utf-8")

    response = minimax.complete(system=SYSTEM_PROMPT, prompt=prompt)
    diff = extract_diff(response.text)
    if args.raw_output:
        Path(args.raw_output).write_text(response.text, encoding="utf-8")
    if not diff:
        print("error: the model answer holds no unified diff", file=sys.stderr)
        print(response.text[:2000], file=sys.stderr)
        return 3

    before = snapshot_files(project_dir, [item["file_path"] for item in context.code])
    try:
        changed = apply_unified_diff(project_dir, diff)
    except Exception as error:  # noqa: BLE001
        print(f"error: the diff could not be applied: {error}", file=sys.stderr)
        if args.raw_output:
            print(f"the model answer was written to {args.raw_output}", file=sys.stderr)
            print(diff, file=sys.stderr)
        return 4

    changed_files = []
    for path in changed:
        relative = path.relative_to(project_dir).as_posix()
        changed_files.append(relative)

    after = snapshot_files(project_dir, changed_files)

    runs: list[Any] = []
    selections = args.tests or list(DEFAULT_TEST_SELECTIONS)
    for selection in selections:
        runs.append(run_tests(project_dir, args.python, selection.split(",")))

    checks = [
        {
            "name": selection,
            "command": " ".join(run.command),
            "exit_code": run.exit_code,
            "passed": run.exit_code == 0,
        }
        for selection, run in zip(selections, runs, strict=False)
    ]
    all_passed = all(run.exit_code == 0 for run in runs)
    changed_labels = [f"changed {relative}" for relative in changed_files]
    done = [*changed_labels, f"ran {len(runs)} test selection(s)"]
    remaining = (
        [] if all_passed else [f"test selection failed: {run.command[-1]}" for run in runs if run.exit_code != 0]
    )

    new_state = build_state(
        task_id=args.task_id,
        objective=args.task,
        scope_id=settings.scope_id,
        context=context,
        done=done,
        remaining=remaining,
        checks=checks,
        artifacts=list(changed_files),
    )

    if not args.no_state_save:
        try:
            resolved_scope = client.ensure_scope()
            client.save_contract(new_state)
            client.save_outcome(new_state)
            client.remember(
                new_state,
                f"SDD task {new_state.task_id}: applied {len(changed_files)} file change(s); "
                f"{len(runs)} test selection(s) executed.",
            )
            new_state.source_ids = dict(new_state.source_ids)
            print(f"Task state written to PowerContext scope {resolved_scope}")
        except RuntimeError as error:
            print(f"warning: the task state could not be written: {error}", file=sys.stderr)

    result = TaskResult(
        task_id=args.task_id,
        context=context,
        response=response,
        diff=diff,
        changed_files=changed_files,
        before=before,
        after=after,
        test_runs=runs,
        state=new_state,
    )
    if args.record:
        Path(args.record).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if args.diff_output:
        Path(args.diff_output).write_text(diff, encoding="utf-8")

    print(f"Changed files: {', '.join(changed_files) or '(none)'}")
    for run in runs:
        print(f"pytest {' '.join(run.command[3:])} -> exit {run.exit_code}")
    return 0 if all(run.exit_code == 0 for run in runs) else 5


def command_state_save(settings: Settings, args: argparse.Namespace) -> int:
    """Write the state of a task into PowerContext.

    Args:
        settings: Runtime settings.
        args: Parsed command line arguments.

    Returns:
        Process exit code.
    """
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    state = TaskState.from_dict(payload)
    client = _powercontext(settings)
    state.scope_id = client.ensure_scope()
    contract_id = client.save_contract(state)
    outcome_id = client.save_outcome(state)
    client.remember(state, f"SDD task {state.task_id}: {state.objective}")
    _print({"task_id": state.task_id, "contract_source": contract_id, "outcome_source": outcome_id})
    return 0


def command_state_show(settings: Settings, args: argparse.Namespace) -> int:
    """Read the state of a task back from PowerContext.

    Args:
        settings: Runtime settings.
        args: Parsed command line arguments.

    Returns:
        Process exit code.
    """
    client = _powercontext(settings)
    client.ensure_scope()
    state = client.read_state(args.task_id)
    if state is None:
        print(f"error: the server holds no state for task {args.task_id}", file=sys.stderr)
        return 6
    _print(state.to_dict())
    return 0


def command_run(settings: Settings, args: argparse.Namespace) -> int:
    """Run the whole flow of a task and write the technical record.

    Args:
        settings: Runtime settings.
        args: Parsed command line arguments.

    Returns:
        Process exit code.
    """
    exit_code = command_apply(settings, args)
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(prog="sddctx", description="SDD context module for software evolution.")
    parser.add_argument("--root", help="Project root that holds specs/ and demo_shop/.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    importer = subparsers.add_parser("import", help="Import the project material into seekDB.")
    importer.add_argument("--specs", help="Directory holding the specification documents.")
    importer.add_argument("--project", help="Root of the business project.")
    importer.set_defaults(handler=command_import)

    context_parser = subparsers.add_parser("context", help="Assemble the development context of a task.")
    context_parser.add_argument("--task", required=True, help="Description of the development task.")
    context_parser.add_argument("--task-id", default="task-1", help="Identifier of the task.")
    context_parser.add_argument("--limit", type=int, default=5, help="Maximum number of specifications.")
    context_parser.add_argument("--json", action="store_true", help="Print the context as JSON.")
    context_parser.add_argument("--output", help="Write the context as JSON to this file.")
    context_parser.add_argument("--no-state", action="store_true", help="Do not read the state from PowerContext.")
    context_parser.set_defaults(handler=command_context)

    applier = subparsers.add_parser("apply", help="Ask MiniMax for a change, apply it and run the tests.")
    applier.add_argument("--task", required=True, help="Description of the development task.")
    applier.add_argument("--task-id", default="task-1", help="Identifier of the task.")
    applier.add_argument("--limit", type=int, default=5, help="Maximum number of specifications.")
    applier.add_argument("--project", help="Root of the business project.")
    applier.add_argument("--python", default=sys.executable, help="Interpreter that runs pytest.")
    applier.add_argument(
        "--tests",
        action="append",
        default=[],
        help="Test selection passed to pytest. Repeatable. Defaults to the target tests of the sample.",
    )
    applier.add_argument("--record", help="Write the technical record as JSON to this file.")
    applier.add_argument("--diff-output", help="Write the applied diff to this file.")
    applier.add_argument("--prompt-output", help="Write the prompt that was sent to MiniMax to this file.")
    applier.add_argument("--no-state-save", action="store_true", help="Do not write the task state into PowerContext.")
    applier.add_argument("--raw-output", help="Write the raw model answer to this file.")
    applier.set_defaults(handler=command_apply)

    state_parser = subparsers.add_parser("state", help="Read and write the state of a task.")
    state_subparsers = state_parser.add_subparsers(dest="state_command", required=True)

    state_save = state_subparsers.add_parser("save", help="Write the state into PowerContext.")
    state_save.add_argument("--file", required=True, help="JSON file that holds the state.")
    state_save.set_defaults(handler=command_state_save)

    state_show = state_subparsers.add_parser("show", help="Read the state back from PowerContext.")
    state_show.add_argument("--task-id", default="task-1", help="Identifier of the task.")
    state_show.set_defaults(handler=command_state_show)

    runner = subparsers.add_parser("run", help="Run the whole flow of a task.")
    runner.add_argument("--task", required=True, help="Description of the development task.")
    runner.add_argument("--task-id", default="task-1", help="Identifier of the task.")
    runner.add_argument("--limit", type=int, default=5, help="Maximum number of specifications.")
    runner.add_argument("--project", help="Root of the business project.")
    runner.add_argument("--python", default=sys.executable, help="Interpreter that runs pytest.")
    runner.add_argument(
        "--tests",
        action="append",
        default=[],
        help="Test selection passed to pytest. Repeatable. Defaults to the target tests of the sample.",
    )
    runner.add_argument("--record", help="Write the technical record as JSON to this file.")
    runner.add_argument("--diff-output", help="Write the applied diff to this file.")
    runner.add_argument("--prompt-output", help="Write the prompt that was sent to MiniMax to this file.")
    runner.add_argument("--no-state-save", action="store_true", help="Do not write the task state into PowerContext.")
    runner.set_defaults(handler=command_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface.

    Args:
        argv: Command line arguments, defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(args.root)
    return int(args.handler(settings, args))


if __name__ == "__main__":
    raise SystemExit(main())
