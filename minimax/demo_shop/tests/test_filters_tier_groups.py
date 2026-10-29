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

"""Target functional tests for SPEC-FILTER-003 customer tier group filtering.

These tests are derived from ``specs/SPEC-FILTER-003.md``. They fail against
the pre-change implementation because the ``premium`` group is not expanded
yet, and they pass once the group expansion is implemented.
"""

from __future__ import annotations

from shop.filters import OrderCriteria, filter_orders


def test_premium_group_expands_to_gold_and_silver(orders) -> None:
    result = filter_orders(orders, OrderCriteria(customer_tiers=frozenset({"premium"})))
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-5"]


def test_exact_tier_still_matches_precisely(orders) -> None:
    result = filter_orders(orders, OrderCriteria(customer_tiers=frozenset({"gold"})))
    assert [order.order_id for order in result] == ["o-1", "o-5"]


def test_group_and_exact_tier_can_be_combined(orders) -> None:
    result = filter_orders(orders, OrderCriteria(customer_tiers=frozenset({"premium", "bronze"})))
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-4", "o-5"]


def test_empty_tier_set_does_not_filter_by_tier(orders) -> None:
    result = filter_orders(orders, OrderCriteria(customer_tiers=frozenset()))
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-3", "o-4", "o-5"]
