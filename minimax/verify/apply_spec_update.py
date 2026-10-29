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

"""Apply or reset the updated specification of the verification sample.

``--apply`` copies the updated specification over the baseline and keeps a
copy of the baseline, ``--reset`` restores the baseline. The module picks the
updated content up after the next import, which shows that the context is
built from the material that is stored, not from a fixed answer.

Usage:
    python verify/apply_spec_update.py --apply
    python verify/apply_spec_update.py --reset
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The specification the sample starts with.
BASELINE = ROOT / "specs" / "SPEC-FILTER-003.md"

#: The updated specification of the sample.
UPDATED = ROOT / "specs" / "updates" / "SPEC-FILTER-003.v2.md"

#: Where the baseline is kept while the update is active.
BACKUP = ROOT / "artifacts" / "SPEC-FILTER-003.baseline.md"


def apply_update() -> int:
    """Replace the baseline with the updated specification.

    Returns:
        Process exit code.
    """
    if not UPDATED.exists():
        print(f"error: the updated specification is missing: {UPDATED}", file=sys.stderr)
        return 1
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if BASELINE.exists() and not BACKUP.exists():
        shutil.copy2(BASELINE, BACKUP)
    shutil.copy2(UPDATED, BASELINE)
    print(f"updated specification applied: {BASELINE} now holds version 2")
    return 0


def reset() -> int:
    """Restore the baseline specification.

    Returns:
        Process exit code.
    """
    if BACKUP.exists():
        shutil.copy2(BACKUP, BASELINE)
        print(f"baseline specification restored: {BASELINE}")
        return 0
    print("no backup found, nothing to reset")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the helper.

    Args:
        argv: Command line arguments.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description="Apply or reset the updated specification.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="Apply the updated specification.")
    group.add_argument("--reset", action="store_true", help="Restore the baseline specification.")
    args = parser.parse_args(argv)
    return apply_update() if args.apply else reset()


if __name__ == "__main__":
    raise SystemExit(main())
