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

"""Apply a unified diff produced by a model.

The applier reads a unified diff, matches every hunk against the current
content of the file and writes the result back. Hunk context is verified
before anything is written, so a diff that does not apply leaves the working
tree untouched.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Matches the file header of a unified diff.
_FILE_HEADER_RE = re.compile(r"^---\s+(?:a/)?(.+?)\s*$", re.MULTILINE)

#: Matches the hunk header of a unified diff.
_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", re.MULTILINE)

#: Matches a fenced code block that carries a diff.
_FENCE_RE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.DOTALL)


class PatchError(RuntimeError):
    """Raised when a diff cannot be applied to the working tree."""


@dataclass
class Hunk:
    """One hunk of a unified diff.

    Attributes:
        old_start: First line of the hunk in the original file.
        old_count: Number of lines the hunk covers in the original file.
        new_start: First line of the hunk in the new file.
        new_count: Number of lines the hunk covers in the new file.
        lines: The body lines of the hunk.
    """

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    """The changes one file of a unified diff carries.

    Attributes:
        path: Path of the file relative to the project root.
        hunks: The hunks of the file.
    """

    path: str
    hunks: list[Hunk] = field(default_factory=list)


def extract_diff(text: str) -> str:
    """Extract the unified diff from a model answer.

    Args:
        text: Raw model answer.

    Returns:
        The unified diff, or an empty string when the answer holds none.
    """
    blocks = _FENCE_RE.findall(text)
    for block in blocks:
        if _HUNK_RE.search(block) and _FILE_HEADER_RE.search(block):
            return block.strip("\n")
    if _HUNK_RE.search(text) and _FILE_HEADER_RE.search(text):
        return text.strip("\n")
    return ""


def parse_unified_diff(diff: str) -> list[FilePatch]:
    """Parse a unified diff into per file patches.

    Args:
        diff: The unified diff.

    Returns:
        One patch per file that the diff changes.

    Raises:
        PatchError: When the diff contains a malformed hunk header.
    """
    patches: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None

    for line in diff.splitlines():
        header = _FILE_HEADER_RE.match(line)
        if header and line.startswith("---"):
            path = header.group(1)
            if path.startswith("b/"):
                path = path[2:]
            current = FilePatch(path=path)
            patches.append(current)
            hunk = None
            continue
        if line.startswith("+++"):
            continue
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            if current is None:
                raise PatchError(f"hunk without a file header: {line!r}")
            hunk = Hunk(
                old_start=int(hunk_match.group(1)),
                old_count=int(hunk_match.group(2) or 1),
                new_start=int(hunk_match.group(3)),
                new_count=int(hunk_match.group(4) or 1),
            )
            current.hunks.append(hunk)
            continue
        if hunk is not None:
            if line.startswith((" ", "+", "-")):
                hunk.lines.append(line)
            elif line == "":
                hunk.lines.append(" ")
            elif line.startswith("\\"):
                continue
            else:
                hunk = None
    return [patch for patch in patches if patch.hunks]


def _hunk_old_lines(hunk: Hunk) -> list[str]:
    """Return the lines a hunk expects in the original file.

    Args:
        hunk: The hunk to inspect.

    Returns:
        The context and removed lines of the hunk.
    """
    return [line[1:] for line in hunk.lines if line[:1] in (" ", "-")]


def _hunk_new_lines(hunk: Hunk) -> list[str]:
    """Return the lines a hunk produces in the patched file.

    Args:
        hunk: The hunk to inspect.

    Returns:
        The context and added lines of the hunk.
    """
    return [line[1:] for line in hunk.lines if line[:1] in (" ", "+")]


def _matches(original: list[str], start: int, expected: list[str]) -> bool:
    """Check whether a block of lines matches the original file.

    Args:
        original: Lines of the original file.
        start: Index the block should start at.
        expected: The lines the block expects.

    Returns:
        ``True`` when the block matches.
    """
    if start < 0 or start + len(expected) > len(original):
        return False
    return all(
        original[start + offset].rstrip("\n") == expected[offset].rstrip("\n") for offset in range(len(expected))
    )


def _locate(original: list[str], hunk: Hunk, window: int = 40) -> int:
    """Find the position of a hunk in the original file.

    The line number of the hunk header is only a hint. A model may count the
    lines of a hunk wrong, so the block of context and removed lines is
    searched around the hint before the hunk is rejected.

    Args:
        original: Lines of the original file.
        hunk: The hunk to place.
        window: Number of lines the search covers on each side of the hint.

    Returns:
        Index the hunk starts at.

    Raises:
        PatchError: When the block of the hunk is not found.
    """
    expected = _hunk_old_lines(hunk)
    if not expected:
        raise PatchError("the hunk holds no context line")
    hint = hunk.old_start - 1
    if _matches(original, hint, expected):
        return hint
    for distance in range(1, window + 1):
        for candidate in (hint - distance, hint + distance):
            if _matches(original, candidate, expected):
                return candidate
    raise PatchError(f"the hunk that starts at line {hunk.old_start} does not match the file content")


def apply_hunks(original: list[str], hunks: list[Hunk], path: str) -> list[str]:
    """Apply hunks to the lines of a file.

    Args:
        original: Lines of the original file.
        hunks: Hunks to apply.
        path: File path used in error messages.

    Returns:
        The lines of the patched file.

    Raises:
        PatchError: When a hunk does not match the original content.
    """
    result: list[str] = []
    cursor = 0
    for hunk in hunks:
        start = _locate(original, hunk)
        if start < cursor:
            raise PatchError(f"overlapping hunks in {path}")
        result.extend(original[cursor:start])
        cursor = start
        for line in hunk.lines:
            marker = line[:1]
            content = line[1:]
            if marker == " ":
                if cursor >= len(original) or original[cursor].rstrip("\n") != content.rstrip("\n"):
                    actual = original[cursor].rstrip("\n") if cursor < len(original) else "<eof>"
                    raise PatchError(
                        f"context mismatch in {path} at line {cursor + 1}: expected {content!r}, found {actual!r}"
                    )
                result.append(original[cursor])
                cursor += 1
            elif marker == "-":
                if cursor >= len(original) or original[cursor].rstrip("\n") != content.rstrip("\n"):
                    actual = original[cursor].rstrip("\n") if cursor < len(original) else "<eof>"
                    raise PatchError(
                        f"removal mismatch in {path} at line {cursor + 1}: expected {content!r}, found {actual!r}"
                    )
                cursor += 1
            elif marker == "+":
                result.append(content + "\n")
    result.extend(original[cursor:])
    return result


def apply_unified_diff(root: Path, diff: str) -> list[Path]:
    """Apply a unified diff to the files below a root directory.

    Args:
        root: Root the paths of the diff are relative to.
        diff: The unified diff.

    Returns:
        The files that were changed.

    Raises:
        PatchError: When the diff cannot be applied.
    """
    patches = parse_unified_diff(diff)
    if not patches:
        raise PatchError("the diff holds no applicable hunk")

    prepared: list[tuple[Path, list[str]]] = []
    for patch in patches:
        target = (root / patch.path).resolve()
        if not str(target).startswith(str(root.resolve())):
            raise PatchError(f"the diff tries to write outside the project root: {patch.path}")
        if not target.exists():
            raise PatchError(f"the diff targets a file that does not exist: {patch.path}")
        original = target.read_text(encoding="utf-8").splitlines(keepends=True)
        patched = apply_hunks(original, patch.hunks, patch.path)
        prepared.append((target, patched))

    changed: list[Path] = []
    for target, patched in prepared:
        target.write_text("".join(patched), encoding="utf-8")
        changed.append(target)
    return changed


def make_unified_diff(before: str, after: str, path: str) -> str:
    """Build a unified diff between two revisions of a file.

    Args:
        before: Original content.
        after: New content.
        path: Path used in the diff header.

    Returns:
        The unified diff.
    """
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)
