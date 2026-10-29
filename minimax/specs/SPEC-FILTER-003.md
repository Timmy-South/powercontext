# SPEC-FILTER-003 客户等级分组筛选

## 需求

`filter_orders` 的 `customer_tiers` 过滤必须同时支持具体等级和等级分组。

具体等级直接按 `Order.customer_tier` 精确匹配。等级分组是等级集合的别名，在过滤前先展开为具体等级集合：

| 分组 | 展开为 |
| --- | --- |
| `premium` | `gold`、`silver` |

传入的具体等级与分组可以混合使用。只要订单的 `customer_tier` 命中展开后的任一等级，该订单即被保留。

当 `customer_tiers` 为空集合时，不按客户等级过滤。

## 适用范围

- `src/shop/filters.py`

## 验收

- `OrderCriteria(customer_tiers=frozenset({"premium"}))` 返回 `customer_tier` 为 `gold` 或 `silver` 的全部订单。
- `OrderCriteria(customer_tiers=frozenset({"gold"}))` 仍然只返回 `customer_tier == "gold"` 的订单。
- `OrderCriteria(customer_tiers=frozenset({"premium", "bronze"}))` 返回 `gold`、`silver`、`bronze` 三种等级的订单。
- 空 `customer_tiers` 返回全部订单。

## 保持不变

`SPEC-FILTER-001` 的状态过滤、`SPEC-FILTER-002` 的金额下限过滤，以及过滤结果相对输入的顺序，
在本次任务中必须保持不变。
