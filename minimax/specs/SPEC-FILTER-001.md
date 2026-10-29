# SPEC-FILTER-001 订单状态筛选

## 需求

`filter_orders` 必须支持按 `status` 过滤订单。传入的 `OrderCriteria.status` 集合中的状态才会被保留；
当 `status` 为空集合时，不按状态过滤。

## 适用范围

- `src/shop/filters.py`

## 验收

- `OrderCriteria(status=frozenset({"paid"}))` 只返回 `status == "paid"` 的订单。
- 空 `status` 集合返回全部订单。
- 过滤不改变输入列表的顺序，也不修改输入对象。

## 保持不变

订单状态取值集合、订单排序规则与 `Order` 数据结构在本次任务中保持不变。
