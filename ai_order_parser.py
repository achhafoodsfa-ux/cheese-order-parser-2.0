# AI adapter: unified multi-order brain with Groq vision/text first, OpenAI fallback.
# Compatibility-safe imports: this adapter must not crash if Streamlit briefly
# has an older cached smart_brain.py during a hot reload.
import smart_brain as _brain

parse_orders_text = _brain.parse_orders_text
parse_orders_image = _brain.parse_orders_image
orders_to_parser_groups = _brain.orders_to_parser_groups


def ai_parse_order_text(text):
    fn = getattr(_brain, "ai_parse_order_text", None)
    if fn is not None:
        return fn(text)
    result = parse_orders_text(text)
    orders = result.get("orders") or []
    first = orders[0] if orders else {"customer_name": "", "items": []}
    return {
        "customer_name": first.get("customer_name", ""),
        "items": first.get("items", []),
        "orders": orders,
        "_fallback": result.get("_fallback", False),
        "_fallback_text": result.get("_fallback_text", ""),
        "_fallback_reason": result.get("_fallback_reason", ""),
    }


def ai_parse_order_image(image_bytes):
    fn = getattr(_brain, "ai_parse_order_image", None)
    if fn is not None:
        return fn(image_bytes)
    result = parse_orders_image(image_bytes)
    orders = result.get("orders") or []
    first = orders[0] if orders else {"customer_name": "", "items": []}
    return {
        "customer_name": first.get("customer_name", ""),
        "items": first.get("items", []),
        "orders": orders,
        "_fallback": result.get("_fallback", False),
        "_fallback_text": result.get("_fallback_text", ""),
        "_fallback_reason": result.get("_fallback_reason", ""),
    }


def ai_to_parser_text(result):
    fn = getattr(_brain, "ai_to_parser_text", None)
    if fn is not None:
        return fn(result)
    if result.get("_fallback"):
        return str(result.get("_fallback_text", ""))
    orders = result.get("orders") or []
    if not orders:
        orders = [{"customer_name": result.get("customer_name", ""), "items": result.get("items", [])}]
    lines = []
    for order in orders:
        if order.get("customer_name"):
            lines.append(str(order["customer_name"]))
        for item in order.get("items", []):
            q = item.get("quantity")
            unit = item.get("unit", "PKT")
            product = item.get("product", "")
            if product and q not in (None, ""):
                lines.append(f"{q} {unit} {product}")
        lines.append("")
    return "\n".join(lines).strip()


__all__ = [
    "ai_parse_order_text",
    "ai_parse_order_image",
    "ai_to_parser_text",
    "orders_to_parser_groups",
    "parse_orders_text",
    "parse_orders_image",
]
