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

"""Restore the code of the business project to its state before the change.

The delivered repository holds the code after the change, because the change
is the result of the task. The snapshot of the code before the change lives
in ``artifacts/code-snapshot-before`` and this script copies it back, so that
the verification sample can be repeated from the state before the change.

Usage:
    python verify/reset_code.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Snapshot of the business project before the change.
SNAPSHOT = ROOT / "artifacts" / "code-snapshot-before"

#: Root of the business project.
PROJECT = ROOT / "demo_shop"


def main() -> int:
    """Restore the snapshot over the business project.

    Returns:
        Process exit code.
    """
    if not SNAPSHOT.exists():
        print(f"error: the snapshot is missing: {SNAPSHOT}", file=sys.stderr)
        return 1
    for source in sorted(SNAPSHOT.rglob("*.py")):
        relative = source.relative_to(SNAPSHOT)
        target = PROJECT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"restored {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
