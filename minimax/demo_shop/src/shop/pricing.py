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

"""Tiered discount calculation."""

from __future__ import annotations

from decimal import Decimal

from shop.models import Order

#: Discount rate applied to the amount above each tier threshold.
_TIER_RATES: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("500"), Decimal("0.10")),
    (Decimal("200"), Decimal("0.05")),
)


def apply_discount(order: Order) -> Decimal:
    """Return the discount amount granted to an order.

    The highest tier whose threshold the order reaches wins. The result is
    never negative and never exceeds the order amount.

    Args:
        order: Order to discount.

    Returns:
        Discount amount in CNY.
    """
    if order.amount <= 0:
        return Decimal("0")
    rate = Decimal("0")
    for threshold, tier_rate in _TIER_RATES:
        if order.amount >= threshold:
            rate = tier_rate
            break
    discount = (order.amount * rate).quantize(Decimal("0.01"))
    return min(discount, order.amount)
