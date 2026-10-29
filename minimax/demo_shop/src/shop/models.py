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

"""Core order model of the demo shop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Order:
    """A single customer order.

    Attributes:
        order_id: Stable business identifier of the order.
        customer_id: Identifier of the customer that placed the order.
        status: Current fulfillment status, for example ``paid`` or ``shipped``.
        amount: Gross order amount in CNY.
        placed_on: Calendar day the order was placed.
        customer_tier: Loyalty tier of the customer, for example ``gold``.
    """

    order_id: str
    customer_id: str
    status: str
    amount: Decimal
    placed_on: date
    customer_tier: str = "standard"
