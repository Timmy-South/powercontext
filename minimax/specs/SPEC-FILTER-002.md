# SPEC-FILTER-002 订单金额下限筛选

## 需求

`filter_orders` 必须支持按 `min_amount` 过滤订单。仅保留 `amount >= min_amount` 的订单。
当 `min_amount` 为 `None` 时，不按金额过滤。

## 适用范围

- `src/shop/filters.py`

## 验收

- `OrderCriteria(min_amount=Decimal("100"))` 只返回金额大于等于 100 的订单。
- 金额比较使用订单自身的 `Decimal` 金额，不做浮点转换。

## 保持不变

金额精度、币种与 `Decimal` 量化方式在本次任务中保持不变。
