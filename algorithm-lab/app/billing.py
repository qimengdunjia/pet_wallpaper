"""文件用途：解析、格式化和汇总可灵任务扣费与资源包额度信息。"""

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation


def parse_decimal(value) -> Decimal | None:
    """安全解析十进制数值；参数为原始字段值，无效或非有限数时返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def format_decimal(value: Decimal) -> str:
    """格式化普通十进制数；参数为有限 Decimal，返回去除多余尾零的字符串。"""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def format_cash(amount: Decimal, currency: str | None) -> str:
    """按币种格式化现金扣费；参数为金额和币种代码，返回可读文本。"""
    code = (currency or "").upper()
    if code in {"CNY", "USD"}:
        # 保留原有高精度小数（如 0.028），常规金额至少展示两位小数。
        trimmed = format_decimal(amount)
        if amount == amount.quantize(Decimal("0.01")) and amount != 0:
            number = format(amount.quantize(Decimal("0.01")), "f")
        else:
            number = trimmed
        prefix = "¥" if code == "CNY" else "$"
        return f"{prefix}{number}"
    return f"余额 {format_decimal(amount)}"


def build_cost_label(unit_total: Decimal | None, cash_by_currency: dict[str, Decimal]) -> str:
    """生成花费展示标签；参数为资源点总量与分币种现金字典，返回简洁文本。"""
    parts = []
    if unit_total is not None and unit_total != 0:
        parts.append(f"{format_decimal(unit_total)} Units")
    for currency, amount in cash_by_currency.items():
        if amount != 0:
            parts.append(format_cash(amount, currency or None))
    if parts:
        return " + ".join(parts)
    if unit_total is not None or cash_by_currency:
        return "0（未扣费）"
    return ""


def _summarize_items(items: list[dict], *, usage: dict | None = None) -> dict | None:
    if not items:
        return None
    unit_total: Decimal | None = None
    cash_by_currency: dict[str, Decimal] = {}
    list_price_by_currency: dict[str, Decimal] = {}
    for item in items:
        amount = parse_decimal(item.get("amount"))
        if amount is None:
            continue
        if item.get("charge_type") == "unit":
            unit_total = (unit_total or Decimal(0)) + amount
        elif item.get("charge_type") == "cash":
            currency = str(item.get("currency") or "").upper()
            cash_by_currency[currency] = cash_by_currency.get(currency, Decimal(0)) + amount
            list_price = parse_decimal(item.get("list_price"))
            if list_price is not None:
                list_price_by_currency[currency] = list_price_by_currency.get(currency, Decimal(0)) + list_price
    if unit_total is None and not cash_by_currency:
        return None
    is_zero = (unit_total or Decimal(0)) == 0 and all(v == 0 for v in cash_by_currency.values())
    result = {
        "source": "api",
        "items": items,
        "unit_amount": format_decimal(unit_total) if unit_total is not None else None,
        "cash_amounts": {cur: format_decimal(val) for cur, val in cash_by_currency.items()},
        "list_price_amounts": {cur: format_decimal(val) for cur, val in list_price_by_currency.items()},
        "is_zero": is_zero,
        "label": build_cost_label(unit_total, cash_by_currency),
    }
    if usage:
        result["usage"] = usage
    return result


def _clean_usage(raw_usage) -> dict | None:
    if not isinstance(raw_usage, dict):
        return None
    cleaned = {}
    for key in ("input_duration", "output_duration"):
        val = parse_decimal(raw_usage.get(key))
        if val is not None:
            cleaned[key] = format_decimal(val)
    return cleaned or None


def extract_task_cost(task: dict) -> dict | None:
    """从可灵任务响应中提取扣费信息；参数为单条任务对象，无计费字段时返回 None。"""
    if not isinstance(task, dict):
        return None
    items: list[dict] = []
    billing = task.get("billing")
    if isinstance(billing, list):
        for entry in billing:
            if not isinstance(entry, dict):
                continue
            charge_type = str(entry.get("charge_type") or "").strip().lower()
            amount = parse_decimal(entry.get("amount"))
            if amount is None:
                continue
            if charge_type == "unit":
                item = {"charge_type": "unit", "amount": format_decimal(amount)}
                if package_type := str(entry.get("package_type") or "").strip():
                    item["package_type"] = package_type
                items.append(item)
            elif charge_type == "cash":
                item = {"charge_type": "cash", "amount": format_decimal(amount)}
                if currency := str(entry.get("currency") or "").strip().upper():
                    item["currency"] = currency
                if cash_type := str(entry.get("cash_type") or "").strip():
                    item["cash_type"] = cash_type
                if (list_price := parse_decimal(entry.get("list_price"))) is not None:
                    item["list_price"] = format_decimal(list_price)
                items.append(item)

    if not items:
        if (unit_val := parse_decimal(task.get("final_unit_deduction"))) is not None:
            items.append({"charge_type": "unit", "amount": format_decimal(unit_val)})
        balance = task.get("final_balance_deduction")
        if isinstance(balance, dict):
            quota = parse_decimal(balance.get("quota"))
            if quota is not None:
                item = {"charge_type": "cash", "amount": format_decimal(quota)}
                if currency := str(balance.get("currency") or "").strip().upper():
                    item["currency"] = currency
                if (list_price := parse_decimal(balance.get("list_price"))) is not None:
                    item["list_price"] = format_decimal(list_price)
                items.append(item)

    return _summarize_items(items, usage=_clean_usage(task.get("usage")))


def aggregate_costs(costs: Iterable[dict | None]) -> dict | None:
    """汇总多条花费记录；参数为花费字典迭代器，无有效记录时返回 None。"""
    unit_total: Decimal | None = None
    cash_by_currency: dict[str, Decimal] = {}
    list_price_by_currency: dict[str, Decimal] = {}
    recorded_count = 0
    for cost in costs:
        if not isinstance(cost, dict):
            continue
        has_entry = False
        if (unit_val := parse_decimal(cost.get("unit_amount"))) is not None:
            unit_total = (unit_total or Decimal(0)) + unit_val
            has_entry = True
        for currency, raw_val in (cost.get("cash_amounts") or {}).items():
            if (val := parse_decimal(raw_val)) is not None:
                code = str(currency or "").upper()
                cash_by_currency[code] = cash_by_currency.get(code, Decimal(0)) + val
                has_entry = True
        for currency, raw_val in (cost.get("list_price_amounts") or {}).items():
            if (val := parse_decimal(raw_val)) is not None:
                code = str(currency or "").upper()
                list_price_by_currency[code] = list_price_by_currency.get(code, Decimal(0)) + val
        if has_entry:
            recorded_count += 1
    if recorded_count == 0:
        return None
    is_zero = (unit_total or Decimal(0)) == 0 and all(v == 0 for v in cash_by_currency.values())
    return {
        "unit_amount": format_decimal(unit_total) if unit_total is not None else None,
        "cash_amounts": {cur: format_decimal(val) for cur, val in cash_by_currency.items()},
        "list_price_amounts": {cur: format_decimal(val) for cur, val in list_price_by_currency.items()},
        "is_zero": is_zero,
        "recorded_count": recorded_count,
        "label": build_cost_label(unit_total, cash_by_currency),
    }


def _classify_pack_category(name: str, applicable_models: str) -> str:
    text = f"{name} {applicable_models}".lower()
    has_image = any(keyword in text for keyword in ("image", "omni-image", "图片", "图像"))
    has_video = any(keyword in text for keyword in ("video", "kling-4", "kling-3", "视频"))
    if has_image and not has_video:
        return "image"
    if has_video and not has_image:
        return "video"
    return "general"


def normalize_resource_packs(raw_infos: list[dict]) -> list[dict]:
    """规范化可灵资源包列表；参数为接口原始数组，返回供前后端展示的结构列表。"""
    packs = []
    for item in raw_infos:
        if not isinstance(item, dict):
            continue
        name = str(item.get("resource_pack_name") or "未命名资源包")
        applicable = str(item.get("resource_pack_applicable_models") or "")
        total = parse_decimal(item.get("total_quantity")) or Decimal(0)
        remaining = parse_decimal(item.get("remaining_quantity")) or Decimal(0)
        packs.append({
            "id": str(item.get("resource_pack_id") or ""),
            "name": name,
            "type": str(item.get("resource_pack_type") or ""),
            "tier": str(item.get("resource_pack_tier") or ""),
            "applicable_models": applicable,
            "category": _classify_pack_category(name, applicable),
            "total_quantity": float(total),
            "remaining_quantity": float(remaining),
            "total_text": format_decimal(total),
            "remaining_text": format_decimal(remaining),
            "purchase_time": item.get("purchase_time"),
            "effective_time": item.get("effective_time"),
            "invalid_time": item.get("invalid_time"),
            "status": str(item.get("status") or ""),
        })
    return packs
