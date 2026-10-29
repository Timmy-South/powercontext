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

"""Regression tests for order filtering.

These cover behavior that already exists and must keep working after any
change to :mod:`shop.filters`.
"""

from __future__ import annotations

from decimal import Decimal

from shop.filters import OrderCriteria, filter_orders


def test_filter_by_status(orders) -> None:
    result = filter_orders(orders, OrderCriteria(status=frozenset({"paid"})))
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-4"]


def test_filter_by_min_amount(orders) -> None:
    result = filter_orders(orders, OrderCriteria(min_amount=Decimal("100")))
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-4"]


def test_filter_combines_status_and_min_amount(orders) -> None:
    result = filter_orders(
        orders,
        OrderCriteria(status=frozenset({"paid"}), min_amount=Decimal("100")),
    )
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-4"]


def test_empty_criteria_returns_every_order(orders) -> None:
    result = filter_orders(orders, OrderCriteria())
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-3", "o-4", "o-5"]


def test_filter_preserves_input_order(orders) -> None:
    result = filter_orders(orders, OrderCriteria(status=frozenset({"paid", "shipped"})))
    assert [order.order_id for order in result] == ["o-1", "o-2", "o-3", "o-4"]


def test_filter_does_not_mutate_input(orders) -> None:
    before = [order.order_id for order in orders]
    filter_orders(orders, OrderCriteria(status=frozenset({"paid"})))
    assert [order.order_id for order in orders] == before


def test_filter_by_exact_customer_tier(orders) -> None:
    result = filter_orders(orders, OrderCriteria(customer_tiers=frozenset({"gold"})))
    assert [order.order_id for order in result] == ["o-1", "o-5"]


def test_filter_by_exact_customer_tier_bronze(orders) -> None:
    result = filter_orders(orders, OrderCriteria(customer_tiers=frozenset({"bronze"})))
    assert [order.order_id for order in result] == ["o-4"]
