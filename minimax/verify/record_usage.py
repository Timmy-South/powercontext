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

"""Record how seekDB and PowerContext were used during the sample.

The script runs the queries that the module uses, writes their result into
``artifacts/db-queries.log`` and reads the task state of PowerContext back
into ``artifacts/powercontext-state.md``. It also stores the code snapshot
before and after the change.

Usage:
    python verify/record_usage.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sddctx.config import load_settings  # noqa: E402
from sddctx.retrieve import build_context, extract_query_terms  # noqa: E402
from sddctx.state import PowerContextClient  # noqa: E402
from sddctx.store import SeekDBStore  # noqa: E402

ARTIFACTS = ROOT / "artifacts"
TASK = "为订单筛选增加客户等级分组过滤：customer_tiers 中的 premium 分组必须展开为 gold 与 silver"
TASK_ID = "task-filter-003"


def record_database_usage(settings) -> Path:
    """Run the queries of the module and write them into the log.

    Args:
        settings: Runtime settings.

    Returns:
        Path of the written log.
    """
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    log_path = ARTIFACTS / "db-queries.log"
    identifiers, phrases = extract_query_terms(TASK)
    lines: list[str] = []
    lines.append("seekDB query record")
    lines.append("=" * 78)
    lines.append(f"database directory: {settings.db_dir}")
    lines.append("")

    with SeekDBStore(settings.db_dir) as store:
        lines.append("-- import run history ------------------------------------------")
        for run in store.import_runs():
            lines.append(json.dumps(run, ensure_ascii=False))
        lines.append("")

        lines.append("-- stored specifications ---------------------------------------")
        for spec in store.all_specs():
            lines.append(
                f"{spec['spec_id']} v{spec['version']} | scope={spec['scope']} | "
                f"source={Path(spec['source_file']).name}:{spec['line_start']} | hash={spec['content_hash'][:16]}"
            )
        lines.append("")

        lines.append("-- revision history of the specifications ------------------------")
        for spec in store.all_specs():
            for version in store.spec_versions(spec["spec_id"]):
                lines.append(f"{spec['spec_id']} v{version['version']} captured={version['captured_at']}")
        lines.append("")

        lines.append("-- retrieval: full text match on the indexed specification text ---")
        query = " ".join(f"+{token}" for token in identifiers)
        lines.append(f"SQL   : SELECT spec_id, MATCH(search_text) AGAINST ('{query}' IN BOOLEAN MODE)")
        rows = store.query(
            """
            SELECT spec_id, MATCH(search_text) AGAINST (%s IN BOOLEAN MODE) AS score
            FROM spec_items
            WHERE MATCH(search_text) AGAINST (%s IN BOOLEAN MODE)
            """,
            (query, query),
        )
        for row in rows:
            lines.append(f"RESULT: spec_id={row[0]} score={float(row[1]):.6f}")
        lines.append("")

        lines.append("-- retrieval: natural language phrase match -----------------------")
        for phrase in phrases:
            lines.append(f"SQL   : SELECT spec_id FROM spec_items WHERE body LIKE '%{phrase}%'")
            for row in store.query(
                "SELECT spec_id FROM spec_items WHERE body LIKE %s OR title LIKE %s",
                (f"%{phrase}%", f"%{phrase}%"),
            ):
                lines.append(f"RESULT: spec_id={row[0]}")
        lines.append("")

        lines.append("-- retrieval: the code symbols of the selected scope ---------------")
        context = build_context(store, TASK, project_dir=settings.project_dir)
        for spec in context.specs:
            lines.append(f"specification {spec.spec_id} declares scope {spec.scope}")
            for symbol in store.symbols_in_scope(spec.scope):
                lines.append(
                    f"  symbol {symbol['symbol_id']} lines {symbol['line_start']}-{symbol['line_end']} kind={symbol['kind']}"
                )
            for test in store.tests_in_scope(spec.scope):
                lines.append(f"  test   {test['test_id']} line {test['line_start']}")
        lines.append("")

        lines.append("-- assembled context ----------------------------------------------")
        lines.append(
            f"specifications={[spec.spec_id for spec in context.specs]} "
            f"code={len(context.code)} tests={len(context.tests)}"
        )

    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


def record_powercontext_usage(settings) -> Path:
    """Read the task state back and write it into the record.

    Args:
        settings: Runtime settings.

    Returns:
        Path of the written record.
    """
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    record_path = ARTIFACTS / "powercontext-state.md"
    client = PowerContextClient(
        base_url=settings.powercontext_url,
        scope_id=settings.scope_id,
        token=settings.powercontext_token,
    )
    scope_id = client.ensure_scope()
    state = client.read_state(TASK_ID)
    hits = client.search_memory(TASK_ID)

    lines: list[str] = []
    lines.append("# PowerContext 状态写入与复用记录")
    lines.append("")
    lines.append(f"- Server: `{settings.powercontext_url}`")
    lines.append(f"- Scope: `{scope_id}`（逻辑名称 `{settings.scope_id}`，作为幂等键使用）")
    lines.append(f"- Task: `{TASK_ID}`")
    lines.append("")
    lines.append("## 写入的 Source")
    lines.append("")
    lines.append("| Source 类型 | Source id | 内容 |")
    lines.append("| --- | --- | --- |")
    lines.append("| work contract | `sddctx-contract:task-filter-003` | 任务目标、事实、范围、排除项、完成条件 |")
    lines.append("| task outcome | `sddctx-outcome:task-filter-003` | 已完成事项、校验结果、待办事项 |")
    lines.append("")
    lines.append("## 读回的原子记忆")
    lines.append("")
    if hits:
        for hit in hits:
            memory = hit.get("memory", {})
            lines.append(f"- `{memory.get('kind', '')}` — {memory.get('text', '')}")
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("## 读回的任务状态")
    lines.append("")
    if state is None:
        lines.append("- （Server 中没有该任务的状态）")
    else:
        lines.append(f"- objective: {state.objective}")
        lines.append(f"- scope_id: {state.scope_id}")
        lines.append(f"- updated_at: {state.updated_at}")
        lines.append("- facts:")
        for fact in state.facts:
            lines.append(f"  - {fact}")
        lines.append("- in_scope:")
        for item in state.in_scope:
            lines.append(f"  - {item}")
        lines.append("- exclusions:")
        for item in state.exclusions:
            lines.append(f"  - {item}")
        lines.append("- done:")
        for item in state.done:
            lines.append(f"  - {item}")
        lines.append("- remaining:")
        for item in state.remaining:
            lines.append(f"  - {item}")
        lines.append("- checks:")
        for check in state.checks:
            lines.append(f"  - {json.dumps(check, ensure_ascii=False)}")
        lines.append(f"- source_ids: {json.dumps(state.source_ids, ensure_ascii=False)}")
    lines.append("")
    record_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return record_path


def record_code_snapshots(settings) -> None:
    """Store the file that the task changed in its current state.

    Args:
        settings: Runtime settings.
    """
    snapshot = ARTIFACTS / "code-snapshot-after"
    target = snapshot / "src" / "shop" / "filters.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    source = settings.project_dir / "src" / "shop" / "filters.py"
    if source.exists():
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> int:
    """Run the recorder.

    Returns:
        Process exit code.
    """
    settings = load_settings(ROOT)
    db_log = record_database_usage(settings)
    print(f"database query record: {db_log}")
    pc_record = record_powercontext_usage(settings)
    print(f"powercontext state record: {pc_record}")
    record_code_snapshots(settings)
    print("code snapshot written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
