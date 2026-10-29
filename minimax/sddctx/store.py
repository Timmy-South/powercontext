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

"""Embedded seekDB storage for engineering material and its index.

The store keeps three kinds of material:

``spec_items``
    SDD specification entries. Every entry carries the identifier taken from
    its document heading, the requirement body, the source file and the line
    range it was parsed from.

``code_symbols``
    Symbols extracted from the business project, joined to specifications
    through the ``scope`` path declared in the specification.

``test_cases``
    Test functions of the business project, linked to the specification that
    covers the same file scope.

The instance is embedded, so the same directory can be reopened by a later
process and the previously imported material is still queryable.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pylibseekdb
import pymysql

#: Database name used inside the embedded seekDB instance.
DATABASE_NAME = "sddctx"

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS spec_items (
        spec_id VARCHAR(64) NOT NULL PRIMARY KEY,
        title VARCHAR(300) NOT NULL,
        body TEXT NOT NULL,
        search_text TEXT NOT NULL,
        scope VARCHAR(400) NOT NULL DEFAULT '',
        version INT NOT NULL DEFAULT 1,
        source_file VARCHAR(400) NOT NULL,
        line_start INT NOT NULL DEFAULT 0,
        line_end INT NOT NULL DEFAULT 0,
        content_hash CHAR(64) NOT NULL,
        updated_at VARCHAR(40) NOT NULL DEFAULT '',
        FULLTEXT KEY ft_spec (search_text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS spec_versions (
        spec_id VARCHAR(64) NOT NULL,
        version INT NOT NULL,
        content_hash CHAR(64) NOT NULL,
        title VARCHAR(300) NOT NULL,
        captured_at VARCHAR(40) NOT NULL,
        PRIMARY KEY (spec_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS code_symbols (
        symbol_id VARCHAR(400) NOT NULL PRIMARY KEY,
        file_path VARCHAR(400) NOT NULL,
        name VARCHAR(200) NOT NULL,
        kind VARCHAR(40) NOT NULL,
        line_start INT NOT NULL DEFAULT 0,
        line_end INT NOT NULL DEFAULT 0,
        snippet TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_cases (
        test_id VARCHAR(400) NOT NULL PRIMARY KEY,
        file_path VARCHAR(400) NOT NULL,
        name VARCHAR(300) NOT NULL,
        line_start INT NOT NULL DEFAULT 0,
        symbol_refs TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS import_runs (
        run_id VARCHAR(64) NOT NULL PRIMARY KEY,
        started_at VARCHAR(40) NOT NULL,
        spec_count INT NOT NULL DEFAULT 0,
        code_count INT NOT NULL DEFAULT 0,
        test_count INT NOT NULL DEFAULT 0
    )
    """,
)


class SeekDBStore:
    """Owns an embedded seekDB instance and exposes the material queries.

    The instance is opened lazily so that constructing the store never leaves a
    background process behind.
    """

    def __init__(self, db_dir: Path | str) -> None:
        """Store the location of the embedded database.

        Args:
            db_dir: Directory that holds the embedded seekDB data.
        """
        self.db_dir = Path(db_dir)
        self._instance: Any | None = None
        self._connection: pymysql.Connection | None = None

    def open(self) -> None:
        """Start the embedded instance and prepare the schema."""
        if self._connection is not None:
            return
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self._instance = pylibseekdb.open(db_dir=str(self.db_dir))
        options = self._instance.connection_options()
        self._connection = pymysql.connect(
            host=options.get("host", "127.0.0.1"),
            port=int(options.get("port") or 0),
            user=options.get("user", "root"),
            password=options.get("password") or "",
            autocommit=True,
            charset="utf8mb4",
        )
        with self.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DATABASE_NAME} DEFAULT CHARACTER SET utf8mb4")
            cursor.execute(f"USE {DATABASE_NAME}")
            for statement in _SCHEMA:
                cursor.execute(statement)

    def close(self) -> None:
        """Stop the embedded instance and release the connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._instance is not None:
            self._instance.close()
            self._instance = None

    def __enter__(self) -> SeekDBStore:
        """Open the store for use."""
        self.open()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        """Close the store on exit."""
        self.close()

    @contextlib.contextmanager
    def cursor(self) -> Iterator[pymysql.cursors.Cursor]:
        """Yield a cursor bound to the active connection."""
        if self._connection is None:
            raise RuntimeError("SeekDBStore.open() must be called before querying")
        cursor = self._connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        """Run a statement and return every row.

        Args:
            sql: Statement to run.
            params: Values bound to the statement.

        Returns:
            Result rows.
        """
        with self.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Run a statement that does not return rows.

        Args:
            sql: Statement to run.
            params: Values bound to the statement.

        Returns:
            Number of affected rows.
        """
        with self.cursor() as cursor:
            return int(cursor.execute(sql, params))

    # ------------------------------------------------------------------
    # Material writes
    # ------------------------------------------------------------------

    def upsert_spec(
        self,
        *,
        spec_id: str,
        title: str,
        body: str,
        search_text: str,
        scope: str,
        version: int,
        source_file: str,
        line_start: int,
        line_end: int,
        content_hash: str,
        updated_at: str,
    ) -> bool:
        """Insert or update one specification entry.

        Args:
            spec_id: Stable specification identifier.
            title: Human readable specification title.
            body: Requirement text of the specification.
            search_text: Text used by the full text index.
            scope: Source path the specification applies to.
            version: Revision number of the specification.
            source_file: File the specification was parsed from.
            line_start: First line of the specification in its file.
            line_end: Last line of the specification in its file.
            content_hash: Hash of the specification body.
            updated_at: Timestamp of the import.

        Returns:
            ``True`` when the stored content changed.
        """
        existing = self.query(
            "SELECT content_hash FROM spec_items WHERE spec_id = %s",
            (spec_id,),
        )
        changed = not existing or existing[0][0] != content_hash
        self.execute(
            """
            INSERT INTO spec_items
                (spec_id, title, body, search_text, scope, version, source_file,
                 line_start, line_end, content_hash, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                body = VALUES(body),
                search_text = VALUES(search_text),
                scope = VALUES(scope),
                version = VALUES(version),
                source_file = VALUES(source_file),
                line_start = VALUES(line_start),
                line_end = VALUES(line_end),
                content_hash = VALUES(content_hash),
                updated_at = VALUES(updated_at)
            """,
            (
                spec_id,
                title,
                body,
                search_text,
                scope,
                version,
                source_file,
                line_start,
                line_end,
                content_hash,
                updated_at,
            ),
        )
        if changed:
            self.execute(
                """
                INSERT INTO spec_versions (spec_id, version, content_hash, title, captured_at)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE captured_at = VALUES(captured_at)
                """,
                (spec_id, version, content_hash, title, updated_at),
            )
        return changed

    def replace_code_symbols(self, symbols: list[dict[str, Any]]) -> None:
        """Replace the stored code symbols with the given set.

        Args:
            symbols: Symbol records to store.
        """
        self.execute("DELETE FROM code_symbols")
        for symbol in symbols:
            self.execute(
                """
                INSERT INTO code_symbols
                    (symbol_id, file_path, name, kind, line_start, line_end, snippet)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    symbol["symbol_id"],
                    symbol["file_path"],
                    symbol["name"],
                    symbol["kind"],
                    symbol["line_start"],
                    symbol["line_end"],
                    symbol["snippet"],
                ),
            )

    def replace_test_cases(self, tests: list[dict[str, Any]]) -> None:
        """Replace the stored test cases with the given set.

        Args:
            tests: Test records to store.
        """
        self.execute("DELETE FROM test_cases")
        for test in tests:
            self.execute(
                """
                INSERT INTO test_cases (test_id, file_path, name, line_start, symbol_refs)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    test["test_id"],
                    test["file_path"],
                    test["name"],
                    test["line_start"],
                    ",".join(test.get("symbol_refs", [])),
                ),
            )

    def record_import_run(
        self, run_id: str, started_at: str, spec_count: int, code_count: int, test_count: int
    ) -> None:
        """Record one import run for auditing.

        Args:
            run_id: Identifier of the run.
            started_at: Timestamp of the run.
            spec_count: Number of imported specifications.
            code_count: Number of imported code symbols.
            test_count: Number of imported test cases.
        """
        self.execute(
            """
            INSERT INTO import_runs (run_id, started_at, spec_count, code_count, test_count)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE started_at = VALUES(started_at)
            """,
            (run_id, started_at, spec_count, code_count, test_count),
        )

    # ------------------------------------------------------------------
    # Material reads
    # ------------------------------------------------------------------

    def all_specs(self) -> list[dict[str, Any]]:
        """Return every stored specification entry."""
        rows = self.query(
            """
            SELECT spec_id, title, body, scope, version, source_file, line_start, line_end, content_hash
            FROM spec_items ORDER BY spec_id
            """
        )
        return [
            {
                "spec_id": row[0],
                "title": row[1],
                "body": row[2],
                "scope": row[3],
                "version": row[4],
                "source_file": row[5],
                "line_start": row[6],
                "line_end": row[7],
                "content_hash": row[8],
            }
            for row in rows
        ]

    def spec_by_id(self, spec_id: str) -> dict[str, Any] | None:
        """Return one stored specification entry.

        Args:
            spec_id: Identifier of the specification.

        Returns:
            The specification record, or ``None`` when it is not stored.
        """
        rows = self.query(
            """
            SELECT spec_id, title, body, scope, version, source_file, line_start, line_end, content_hash
            FROM spec_items WHERE spec_id = %s
            """,
            (spec_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "spec_id": row[0],
            "title": row[1],
            "body": row[2],
            "scope": row[3],
            "version": row[4],
            "source_file": row[5],
            "line_start": row[6],
            "line_end": row[7],
            "content_hash": row[8],
        }

    def spec_versions(self, spec_id: str) -> list[dict[str, Any]]:
        """Return the recorded revisions of one specification.

        Args:
            spec_id: Identifier of the specification.

        Returns:
            Revision records ordered by version.
        """
        rows = self.query(
            """
            SELECT version, content_hash, title, captured_at
            FROM spec_versions WHERE spec_id = %s ORDER BY version
            """,
            (spec_id,),
        )
        return [{"version": row[0], "content_hash": row[1], "title": row[2], "captured_at": row[3]} for row in rows]

    def symbols_in_scope(self, scope: str) -> list[dict[str, Any]]:
        """Return the code symbols that live in a source path.

        Args:
            scope: Source path declared by a specification.

        Returns:
            Symbol records ordered by their position in the file.
        """
        rows = self.query(
            """
            SELECT symbol_id, file_path, name, kind, line_start, line_end, snippet
            FROM code_symbols WHERE file_path = %s ORDER BY line_start
            """,
            (scope,),
        )
        return [
            {
                "symbol_id": row[0],
                "file_path": row[1],
                "name": row[2],
                "kind": row[3],
                "line_start": row[4],
                "line_end": row[5],
                "snippet": row[6],
            }
            for row in rows
        ]

    def tests_in_scope(self, scope: str) -> list[dict[str, Any]]:
        """Return the test cases that belong to a source path.

        A test belongs to a scope when the body of the test refers to one of
        the symbols of that scope. The relation is therefore established by
        the code the test exercises rather than by the location of the file.

        Args:
            scope: Source path declared by a specification.

        Returns:
            Test records ordered by their position in the file.
        """
        symbol_names = [symbol["name"] for symbol in self.symbols_in_scope(scope)]
        if not symbol_names:
            return []
        conditions = " OR ".join(["symbol_refs LIKE %s"] * len(symbol_names))
        params: tuple[Any, ...] = tuple(f"%{name}%" for name in symbol_names)
        rows = self.query(
            f"""
            SELECT test_id, file_path, name, line_start
            FROM test_cases WHERE {conditions} ORDER BY file_path, line_start
            """,
            params,
        )
        return [{"test_id": row[0], "file_path": row[1], "name": row[2], "line_start": row[3]} for row in rows]

    def all_code_symbols(self) -> list[dict[str, Any]]:
        """Return every stored code symbol."""
        rows = self.query(
            """
            SELECT symbol_id, file_path, name, kind, line_start, line_end, snippet
            FROM code_symbols ORDER BY file_path, line_start
            """
        )
        return [
            {
                "symbol_id": row[0],
                "file_path": row[1],
                "name": row[2],
                "kind": row[3],
                "line_start": row[4],
                "line_end": row[5],
                "snippet": row[6],
            }
            for row in rows
        ]

    def all_test_cases(self) -> list[dict[str, Any]]:
        """Return every stored test case."""
        rows = self.query("SELECT test_id, file_path, name, line_start FROM test_cases ORDER BY file_path, line_start")
        return [{"test_id": row[0], "file_path": row[1], "name": row[2], "line_start": row[3]} for row in rows]

    def import_runs(self) -> list[dict[str, Any]]:
        """Return the recorded import runs, newest first."""
        rows = self.query(
            """
            SELECT run_id, started_at, spec_count, code_count, test_count
            FROM import_runs ORDER BY started_at DESC
            """
        )
        return [
            {
                "run_id": row[0],
                "started_at": row[1],
                "spec_count": row[2],
                "code_count": row[3],
                "test_count": row[4],
            }
            for row in rows
        ]
