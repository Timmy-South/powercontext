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

"""Tests for the seekDB store and the retrieval of the context module.

The tests run against a real embedded seekDB instance, so they cover the
behaviour the module depends on: the material is stored, the full text index
finds it and an updated specification replaces the stored one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sddctx.ingest import import_materials
from sddctx.retrieve import build_context, extract_query_terms, select_specs
from sddctx.store import SeekDBStore

SPEC_TIER = """# SPEC-FILTER-003 客户等级分组筛选

## 需求

`filter_orders` 的 `customer_tiers` 过滤必须支持 `premium` 分组展开为 gold 与 silver。

## 适用范围

- `src/shop/filters.py`

## 验收

- `OrderCriteria(customer_tiers=frozenset({"premium"}))` 返回 gold 或 silver 的订单。

## 保持不变

状态过滤必须保持不变。
"""

SPEC_PRICE = """# SPEC-PRICE-010 阶梯折扣计算

## 需求

`apply_discount` 按订单金额计算阶梯折扣。

## 适用范围

- `src/shop/pricing.py`

## 验收

- 金额达到 500 时按 10% 计算折扣。

## 保持不变

折扣率保持不变。
"""

SOURCE = """class OrderCriteria:
    \"\"\"Criteria.\"\"\"


def filter_orders(orders, criteria):
    \"\"\"Filter orders.\"\"\"
    return list(orders)
"""

TEST_SOURCE = """from shop.filters import filter_orders


def test_filter_orders_returns_orders():
    assert filter_orders([], None) == []
"""


@pytest.fixture
def project(tmp_path) -> Path:
    """Build a small project with one specification and one test.

    Args:
        tmp_path: Directory of the fixture.

    Returns:
        Root of the project.
    """
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "SPEC-FILTER-003.md").write_text(SPEC_TIER, encoding="utf-8")
    (specs / "SPEC-PRICE-010.md").write_text(SPEC_PRICE, encoding="utf-8")

    source = tmp_path / "demo" / "src" / "shop"
    source.mkdir(parents=True)
    (source / "filters.py").write_text(SOURCE, encoding="utf-8")
    (source / "pricing.py").write_text(SOURCE, encoding="utf-8")

    tests = tmp_path / "demo" / "tests"
    tests.mkdir()
    (tests / "test_filters.py").write_text(TEST_SOURCE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def store(tmp_path) -> SeekDBStore:
    """Provide an open store with a temporary database.

    Args:
        tmp_path: Directory of the fixture.

    Yields:
        The open store.
    """
    instance = SeekDBStore(tmp_path / "seekdb")
    instance.open()
    try:
        yield instance
    finally:
        instance.close()


def test_import_stores_the_material(store, project) -> None:
    summary = import_materials(
        store,
        specs_dir=project / "specs",
        project_dir=project / "demo",
    )
    assert summary["spec_count"] == 2
    assert summary["code_symbol_count"] >= 2
    assert summary["test_count"] == 1

    specs = {spec["spec_id"]: spec for spec in store.all_specs()}
    assert set(specs) == {"SPEC-FILTER-003", "SPEC-PRICE-010"}
    assert specs["SPEC-FILTER-003"]["scope"] == "src/shop/filters.py"
    assert specs["SPEC-FILTER-003"]["source_file"].endswith("SPEC-FILTER-003.md")


def test_retrieval_selects_the_specification_of_the_task(store, project) -> None:
    import_materials(store, specs_dir=project / "specs", project_dir=project / "demo")
    selected = select_specs(store, "为 customer_tiers 增加 premium 分组展开")
    assert selected
    assert selected[0].spec_id == "SPEC-FILTER-003"
    assert "fulltext" in selected[0].matched_by


def test_the_context_points_at_the_code_and_the_tests(store, project) -> None:
    import_materials(store, specs_dir=project / "specs", project_dir=project / "demo")
    context = build_context(store, "customer_tiers premium 分组", project_dir=project / "demo")
    assert context.specs
    assert any(item["name"] == "filter_orders" for item in context.code)
    assert any(item["name"] == "test_filter_orders_returns_orders" for item in context.tests)
    assert context.files
    assert context.files[0]["file_path"] == "src/shop/filters.py"
    assert "filter_orders" in context.files[0]["content"]


def test_an_updated_specification_replaces_the_stored_one(store, project) -> None:
    import_materials(store, specs_dir=project / "specs", project_dir=project / "demo")
    first = store.spec_by_id("SPEC-FILTER-003")
    assert first is not None
    assert first["version"] == 1

    updated = SPEC_TIER.replace(
        "`premium` 分组展开为 gold 与 silver",
        "`premium` 分组展开为 gold 与 silver，`standard` 分组展开为 bronze 与 standard",
    )
    (project / "specs" / "SPEC-FILTER-003.md").write_text(updated, encoding="utf-8")
    import_materials(store, specs_dir=project / "specs", project_dir=project / "demo")

    second = store.spec_by_id("SPEC-FILTER-003")
    assert second is not None
    assert second["version"] == 2
    assert "standard" in second["body"]
    assert len(store.spec_versions("SPEC-FILTER-003")) == 2

    context = build_context(store, "customer_tiers premium 分组", project_dir=project / "demo")
    spec = next(spec for spec in context.specs if spec.spec_id == "SPEC-FILTER-003")
    assert spec.version == 2
    assert "standard" in spec.body


def test_the_store_keeps_the_material_across_a_reopen(tmp_path, project) -> None:
    database = tmp_path / "seekdb"
    first = SeekDBStore(database)
    first.open()
    try:
        import_materials(first, specs_dir=project / "specs", project_dir=project / "demo")
    finally:
        first.close()

    second = SeekDBStore(database)
    second.open()
    try:
        assert len(second.all_specs()) == 2
        assert second.spec_by_id("SPEC-FILTER-003") is not None
    finally:
        second.close()


def test_extract_query_terms_splits_identifiers_and_phrases() -> None:
    identifiers, phrases = extract_query_terms("为 customer_tiers 增加 premium 分组展开")
    assert "customer_tiers" in identifiers
    assert "premium" in identifiers
    assert phrases
