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

"""Tests for the unified diff applier."""

from __future__ import annotations

import pytest
from sddctx.patch import (
    PatchError,
    apply_hunks,
    apply_unified_diff,
    extract_diff,
    make_unified_diff,
    parse_unified_diff,
)

ORIGINAL = "alpha\nbeta\ngamma\ndelta\n"


def test_extract_diff_reads_a_fenced_block() -> None:
    answer = "Here is the change:\n\n```diff\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-alpha\n+beta\n```\n"
    diff = extract_diff(answer)
    assert "--- a/x.py" in diff
    assert "-alpha" in diff


def test_extract_diff_accepts_a_plain_diff() -> None:
    answer = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-alpha\n+beta\n"
    assert "-alpha" in extract_diff(answer)


def test_extract_diff_returns_empty_for_other_answers() -> None:
    assert extract_diff("I could not change the code.") == ""


def test_parse_unified_diff_reads_the_file_and_the_hunks() -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,2 +1,3 @@\n alpha\n+beta\n gamma\n"
    patches = parse_unified_diff(diff)
    assert len(patches) == 1
    assert patches[0].path == "src/x.py"
    assert len(patches[0].hunks) == 1


def test_apply_hunks_keeps_the_untouched_lines() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n-alpha\n+ALPHA\n beta\n"
    patches = parse_unified_diff(diff)
    result = apply_hunks(ORIGINAL.splitlines(keepends=True), patches[0].hunks, "x.py")
    assert "".join(result) == "ALPHA\nbeta\ngamma\ndelta\n"


def test_apply_hunks_locates_a_hunk_with_a_wrong_line_number() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@ -9,2 +9,2 @@\n-gamma\n+GAMMA\n delta\n"
    patches = parse_unified_diff(diff)
    result = apply_hunks(ORIGINAL.splitlines(keepends=True), patches[0].hunks, "x.py")
    assert "".join(result) == "alpha\nbeta\nGAMMA\ndelta\n"


def test_apply_hunks_rejects_content_that_does_not_match() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-missing\n+other\n"
    patches = parse_unified_diff(diff)
    with pytest.raises(PatchError):
        apply_hunks(ORIGINAL.splitlines(keepends=True), patches[0].hunks, "x.py")


def test_apply_unified_diff_writes_the_file(tmp_path) -> None:
    target = tmp_path / "x.py"
    target.write_text(ORIGINAL, encoding="utf-8")
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,2 @@\n-alpha\n+ALPHA\n+extra\n"
    changed = apply_unified_diff(tmp_path, diff)
    assert changed == [target.resolve()]
    assert target.read_text(encoding="utf-8") == "ALPHA\nextra\nbeta\ngamma\ndelta\n"


def test_apply_unified_diff_refuses_a_path_outside_the_root(tmp_path) -> None:
    target = tmp_path / "x.py"
    target.write_text(ORIGINAL, encoding="utf-8")
    diff = "--- a/../escape.py\n+++ b/../escape.py\n@@ -1,1 +1,1 @@\n-alpha\n+beta\n"
    with pytest.raises(PatchError):
        apply_unified_diff(tmp_path, diff)


def test_make_unified_diff_reports_the_change() -> None:
    diff = make_unified_diff("a\nb\n", "a\nc\n", "x.py")
    assert "-b" in diff
    assert "+c" in diff
