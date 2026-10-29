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

"""Tests for the specification parser and the code and test collection."""

from __future__ import annotations

from sddctx.ingest import build_search_text, collect_symbols, collect_tests, parse_spec_file

SPEC_TEXT = """# SPEC-FILTER-003 客户等级分组筛选

## 需求

`filter_orders` 的 `customer_tiers` 过滤必须同时支持具体等级和等级分组。

## 适用范围

- `src/shop/filters.py`

## 验收

- `OrderCriteria(customer_tiers=frozenset({"premium"}))` 返回 `gold` 或 `silver` 的订单。

## 保持不变

`SPEC-FILTER-001` 的状态过滤必须保持不变。
"""

SOURCE = """\"\"\"Module docstring.\"\"\"


class Widget:
    \"\"\"A widget.\"\"\"

    def render(self) -> str:
        \"\"\"Render the widget.\"\"\"
        return "widget"


def build_widget() -> Widget:
    \"\"\"Build a widget.\"\"\"
    return Widget()
"""

TEST_SOURCE = """from shop.filters import filter_orders


def test_filters_orders():
    assert filter_orders([], None) == []


def test_other_thing():
    assert True
"""


def test_parse_spec_file_reads_every_section(tmp_path) -> None:
    path = tmp_path / "SPEC-FILTER-003.md"
    path.write_text(SPEC_TEXT, encoding="utf-8")
    spec = parse_spec_file(path)
    assert spec is not None
    assert spec.spec_id == "SPEC-FILTER-003"
    assert spec.title == "客户等级分组筛选"
    assert "customer_tiers" in spec.requirement
    assert spec.scopes == ["src/shop/filters.py"]
    assert spec.acceptance and spec.invariants
    assert spec.line_start == 1


def test_parse_spec_file_ignores_a_document_without_an_identifier(tmp_path) -> None:
    path = tmp_path / "README.md"
    path.write_text("# Notes\n\nsome text\n", encoding="utf-8")
    assert parse_spec_file(path) is None


def test_build_search_text_carries_the_identifier_and_the_requirement(tmp_path) -> None:
    path = tmp_path / "SPEC.md"
    path.write_text(SPEC_TEXT, encoding="utf-8")
    spec = parse_spec_file(path)
    assert spec is not None
    search_text = build_search_text(spec)
    assert "SPEC-FILTER-003" in search_text
    assert "customer_tiers" in search_text
    assert "src/shop/filters.py" in search_text


def test_collect_symbols_finds_the_functions_and_the_classes(tmp_path) -> None:
    source = tmp_path / "src" / "shop"
    source.mkdir(parents=True)
    (source / "widget.py").write_text(SOURCE, encoding="utf-8")
    symbols = collect_symbols(tmp_path)
    names = {symbol["name"] for symbol in symbols}
    assert {"Widget", "render", "build_widget"} <= names
    widget = next(symbol for symbol in symbols if symbol["name"] == "Widget")
    assert widget["kind"] == "class"
    assert widget["file_path"] == "src/shop/widget.py"


def test_collect_tests_records_the_symbols_a_test_refers_to(tmp_path) -> None:
    source = tmp_path / "src" / "shop"
    source.mkdir(parents=True)
    (source / "widget.py").write_text(SOURCE, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_widget.py").write_text(TEST_SOURCE, encoding="utf-8")
    tests = collect_tests(tmp_path, ["filter_orders", "Widget"])
    by_name = {test["name"]: test for test in tests}
    assert set(by_name) == {"test_filters_orders", "test_other_thing"}
    assert by_name["test_filters_orders"]["symbol_refs"] == ["filter_orders"]
    assert by_name["test_other_thing"]["symbol_refs"] == []
