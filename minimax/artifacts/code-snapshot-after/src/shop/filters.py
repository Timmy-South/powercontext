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

"""Order filtering helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from shop.models import Order


_CUSTOMER_TIER_GROUPS = {
    "premium": frozenset({"gold", "silver"}),
}


@dataclass(frozen=True)
class OrderCriteria:
    """Filter criteria accepted by :func:`filter_orders`.

    Attributes:
        status: Keep only orders whose status is in this collection.
        min_amount: Keep only orders whose amount is greater than or equal to it.
        customer_tiers: Keep only orders whose customer tier is in this collection.
    """

    status: frozenset[str] = field(default_factory=frozenset)
    min_amount: Decimal | None = None
    customer_tiers: frozenset[str] = field(default_factory=frozenset)


def filter_orders(orders: Iterable[Order], criteria: OrderCriteria) -> list[Order]:
    """Return the orders that satisfy every configured criterion.

    Args:
        orders: Orders to filter.
        criteria: Criteria that an order must satisfy.

    Returns:
        Matching orders in their original relative order.
    """
    result = list(orders)
    if criteria.status:
        result = [order for order in result if order.status in criteria.status]
    if criteria.min_amount is not None:
        result = [order for order in result if order.amount >= criteria.min_amount]
    if criteria.customer_tiers:
        customer_tiers = set(criteria.customer_tiers)
        for group, expanded_tiers in _CUSTOMER_TIER_GROUPS.items():
            if group in customer_tiers:
                customer_tiers.remove(group)
                customer_tiers.update(expanded_tiers)
        result = [order for order in result if order.customer_tier in customer_tiers]
    return result
