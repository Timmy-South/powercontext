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

"""Shared fixtures for the demo shop test suite."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from shop.models import Order

ORDERS = [
    Order("o-1", "c-1", "paid", Decimal("120.00"), date(2026, 3, 1), "gold"),
    Order("o-2", "c-2", "paid", Decimal("480.00"), date(2026, 3, 2), "silver"),
    Order("o-3", "c-3", "shipped", Decimal("60.00"), date(2026, 3, 3), "standard"),
    Order("o-4", "c-4", "paid", Decimal("760.00"), date(2026, 3, 4), "bronze"),
    Order("o-5", "c-5", "cancelled", Decimal("35.00"), date(2026, 3, 5), "gold"),
]


@pytest.fixture
def orders() -> list[Order]:
    """Return a fixed list of orders covering every status and tier."""
    return list(ORDERS)
