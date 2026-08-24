import base64
import io
import json
import os
import re
from typing import Any, Dict, List

from PIL import Image, ImageFilter, ImageOps
import pytesseract
from openai import OpenAI, RateLimitError, APIError, APITimeoutError, APIConnectionError

GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

SCHEMA = {
    "type": "object",
    "properties": {
        "orders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "raw_text": {"type": "string"},
                                "product": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string", "enum": ["CTN", "PKT", "KG", "PCS"]},
                            },
                            "required": ["raw_text", "product", "quantity", "unit"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["customer_name", "items"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["orders"],
    "additionalProperties": False,
}

INSTRUCTIONS = """
You are the reasoning brain for a cheese order parser.
Your job is UNDERSTANDING, not final SAP-code assignment.

MULTI-CUSTOMER WHATSAPP SCREENSHOT RULES:
1. A screenshot may contain 1 customer or MANY customers. 10+ customer orders in one screenshot is normal.
2. Read the ENTIRE image from top to bottom. Do not stop after the first visible order.
3. Identify every WhatsApp sender/customer name, chat heading, sender label, or clear order block.
4. Treat each distinct customer/order block as a separate object in orders[]. NEVER merge different customers.
5. Keep every product line attached to the customer whose message/block contains it.
6. If the same customer appears more than once in the screenshot, keep those messages under the same customer only when the identity is clear; otherwise keep separate blocks rather than guessing.
7. Preserve the customer name exactly as visible when possible.
8. Customer codes/BP/CFS numbers are NOT product identifiers. Ignore them for product lookup.
9. Never invent FG/SAP codes. Final FG mapping is performed by the local product master/rules.
10. Do not return a single generic order just because multiple names are hard to read. Make your best effort to identify every visible order.

IMAGE READING RULES:
- Inspect the original image visually AND use any OCR text supplied in the user message as a cross-check.
- WhatsApp UI text such as time, ticks, phone numbers, delivery notes, greetings, addresses and dates is not an order item.
- A sender/customer name followed by one or more product lines defines an order block.
- Keep each block independent even when the same product is requested by several customers.

PRODUCT UNDERSTANDING RULES:
- Classic shredd / classic shredded = Classic Mozzarella Shredded. Local rule: FG-02-0036.
- 50/50 shredd / 50/50 shredded = Imported 50/50 Mozzarella/Cheddar Shredded 2 KG. Local rule: FG-03-0024.
- For TOP COW ONLY: White Shredded = White Dice; Yellow Shredded = Yellow Dice.
- For every other product, Dice, Shredded and Block are distinct and must not be substituted.
- Achha White Dice = Achha White Dice (local rule FG-01-0124).
- Box, boxes, carton, cartons and CTN are the same unit: CTN.
- Ignore ratios/weights embedded in product names as quantities: 70/30, 50/50, 2kg, 2.5kg, 1kg, 800gm, etc. are product attributes unless an explicit order quantity is stated.
- Quantity must be taken from the explicit quantity/unit expression, preferably the number immediately associated with CTN/box/carton/pkt/pcs/kg.
- Example: "70/30 shredded local 10 ctn" means quantity 10 CTN, NOT 70.
- Ignore prices, invoice numbers, phone numbers, dates and unrelated chatter.
""".strip()


def _secret(name: str) -> str | None:
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name)


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("AI response was not an object")
    return data


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    orders: List[Dict[str, Any]] = []
    for order in data.get("orders", []):
        customer = str(order.get("customer_name", "")).strip()
        items = []
        for item in order.get("items", []):
            product = str(item.get("product", "")).strip()
            if not product:
                continue
            items.append({
                "raw_text": str(item.get("raw_text", "")).strip(),
                "product": product,
                "quantity": item.get("quantity"),
                "unit": str(item.get("unit", "PKT")).upper(),
            })
        if customer or items:
            orders.append({"customer_name": customer, "items": items})
    return {"orders": orders}


def _fallback(text: str, reason: str) -> Dict[str, Any]:
    return {
        "orders": [{"customer_name": "", "items": []}],
        "_fallback": True,
        "_fallback_text": text,
        "_fallback_reason": reason,
    }


def _prepare_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Normalize screenshot size/contrast so tiny WhatsApp text is easier to read."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    max_dim = max(width, height)
    target_min = 2800
    if max_dim < target_min:
        scale = target_min / max_dim
        image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    elif max_dim > 5500:
        scale = 5500 / max_dim
        image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.SHARPEN)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue(), "image/jpeg"


def _ocr_image(image_bytes: bytes) -> str:
    """OCR the screenshot as a second reading channel for small chat text."""
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        if max(width, height) < 3000:
            scale = 3000 / max(width, height)
            image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
        gray = ImageOps.grayscale(image)
        gray = ImageOps.autocontrast(gray)
        gray = gray.filter(ImageFilter.SHARPEN)
        parts = []
        for psm in (6, 11):
            txt = pytesseract.image_to_string(gray, config=f"--psm {psm}")
            if txt.strip():
                parts.append(txt.strip())
        return "\n\n--- OCR PASS ---\n\n".join(parts)
    except Exception:
        return ""


def _call_groq_text(text: str) -> Dict[str, Any]:
    key = _secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": text}],
        response_format={"type": "json_object"}, temperature=0, max_tokens=12000,
    )
    return _normalize(_parse_json(response.choices[0].message.content))


def _call_groq_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    key = _secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    prepared, prepared_mime = _prepare_image(image_bytes)
    ocr_text = _ocr_image(prepared)
    data_url = f"data:{prepared_mime};base64," + base64.b64encode(prepared).decode("ascii")
    prompt = """Read this WhatsApp screenshot completely from top to bottom.

Create one separate order object for EVERY distinct customer/order block visible in the screenshot. Do not stop after the first customer. Make sure every product line and quantity is attached to the correct customer.

Use the OCR transcript below only as a reading aid. The image itself is authoritative when OCR is noisy.

OCR TRANSCRIPT:
---
%s
---

Return ALL orders in the required JSON structure.""" % (ocr_text or "[No OCR text available]")
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        response_format={"type": "json_object"}, temperature=0, max_tokens=12000,
    )
    return _normalize(_parse_json(response.choices[0].message.content))


def _call_openai_text(text: str) -> Dict[str, Any]:
    key = _secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=key)
    response = client.responses.create(
        model=OPENAI_MODEL, store=False, instructions=INSTRUCTIONS, input=text,
        text={"format": {"type": "json_schema", "name": "cheese_orders", "schema": SCHEMA, "strict": True}},
    )
    return _normalize(_parse_json(response.output_text))


def _call_openai_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    key = _secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=key)
    prepared, prepared_mime = _prepare_image(image_bytes)
    ocr_text = _ocr_image(prepared)
    data_url = f"data:{prepared_mime};base64," + base64.b64encode(prepared).decode("ascii")
    prompt = """Read the ENTIRE WhatsApp screenshot from top to bottom. Extract EVERY distinct customer/order block, not just the first one. Keep each customer's products and quantities separate.

Use this OCR transcript as a second reading channel, but trust the screenshot when OCR is wrong:
---
%s
---

Return ALL customer orders in the required JSON structure.""" % (ocr_text or "[No OCR text available]")
    response = client.responses.create(
        model=OPENAI_MODEL, store=False, instructions=INSTRUCTIONS,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": data_url, "detail": "high"},
        ]}],
        text={"format": {"type": "json_schema", "name": "cheese_orders", "schema": SCHEMA, "strict": True}},
    )
    return _normalize(_parse_json(response.output_text))


def _run(primary, secondary, fallback_text: str):
    try:
        return primary()
    except (RateLimitError, APIError, APITimeoutError, APIConnectionError, RuntimeError, ValueError, json.JSONDecodeError):
        try:
            return secondary()
        except Exception as exc:
            return _fallback(fallback_text, f"AI providers unavailable: {type(exc).__name__}")


def parse_orders_text(text: str) -> Dict[str, Any]:
    return _run(lambda: _call_groq_text(text), lambda: _call_openai_text(text), text)


def parse_orders_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    return _run(lambda: _call_groq_image(image_bytes, mime), lambda: _call_openai_image(image_bytes, mime), "")


def orders_to_parser_groups(result: Dict[str, Any]) -> List[Dict[str, str]]:
    if result.get("_fallback"):
        return [{"customer_name": "", "parser_text": str(result.get("_fallback_text", ""))}]
    groups = []
    for order in result.get("orders", []):
        lines = [str(order.get("customer_name", "")).strip()]
        for item in order.get("items", []):
            q = item.get("quantity")
            unit = item.get("unit", "PKT")
            product = item.get("product", "")
            if product and q not in (None, ""):
                lines.append(f"{q} {unit} {product}")
        if len(lines) > 1:
            groups.append({"customer_name": lines[0], "parser_text": "\n".join(lines)})
    return groups


def ai_parse_order_text(text: str) -> Dict[str, Any]:
    result = parse_orders_text(text)
    if result.get("orders"):
        first = result["orders"][0]
        return {"customer_name": first.get("customer_name", ""), "items": first.get("items", []), "orders": result.get("orders", []), "_fallback": result.get("_fallback", False), "_fallback_text": result.get("_fallback_text", ""), "_fallback_reason": result.get("_fallback_reason", "")}
    return result


def ai_parse_order_image(image_bytes: bytes) -> Dict[str, Any]:
    result = parse_orders_image(image_bytes)
    if result.get("orders"):
        first = result["orders"][0]
        return {"customer_name": first.get("customer_name", ""), "items": first.get("items", []), "orders": result.get("orders", []), "_fallback": result.get("_fallback", False), "_fallback_text": result.get("_fallback_text", ""), "_fallback_reason": result.get("_fallback_reason", "")}
    return result


def ai_to_parser_text(result: Dict[str, Any]) -> str:
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
            q = item.get("quantity"); unit = item.get("unit", "PKT"); product = item.get("product", "")
            if product and q not in (None, ""):
                lines.append(f"{q} {unit} {product}")
        lines.append("")
    return "\n".join(lines).strip()
