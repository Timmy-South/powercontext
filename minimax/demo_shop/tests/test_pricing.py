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

"""Regression tests for tiered discount calculation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from shop.models import Order
from shop.pricing import apply_discount


def _order(amount: str) -> Order:
    return Order("o-x", "c-x", "paid", Decimal(amount), date(2026, 3, 1))


def test_top_tier_discount() -> None:
    assert apply_discount(_order("500")) == Decimal("50.00")


def test_middle_tier_discount() -> None:
    assert apply_discount(_order("200")) == Decimal("10.00")


def test_below_tier_has_no_discount() -> None:
    assert apply_discount(_order("199.99")) == Decimal("0")


def test_discount_never_exceeds_order_amount() -> None:
    assert apply_discount(_order("500")) <= Decimal("500")


def test_non_positive_amount_has_no_discount() -> None:
    assert apply_discount(_order("0")) == Decimal("0")
