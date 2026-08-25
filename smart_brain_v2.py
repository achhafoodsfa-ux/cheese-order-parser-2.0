import base64
import json
import os
import re
from typing import Any, Dict, List

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

SYSTEM = r'''
You are the order-understanding brain for a cheese order parser.

YOUR ONLY JOB:
1) Identify the CUSTOMER / ORDER OWNER.
2) Identify PRODUCT + EXPLICIT ORDER QUANTITY.
Everything else is irrelevant and MUST be ignored.

MULTI-CUSTOMER WHATSAPP SCREENSHOT — HARD RULES:
- One screenshot can contain 1, 5, 10, 20+ customers.
- Read the ENTIRE image from top to bottom before producing output.
- FIRST identify each customer/order block. THEN extract only product lines inside that block.
- Every distinct customer/order block MUST become its own orders[] object.
- NEVER merge two customers just because they ordered the same product.
- NEVER move a product line from one customer to another.
- If customer identity is visible, preserve it.
- If a line is not clearly attached to a customer, do not guess a customer; keep it out rather than merging.

IGNORE ALL NON-ORDER CONTENT:
- WhatsApp timestamps: 10:31 PM, 10:31, 10:31 PM V, etc.
- Forwarded / - Forwarded
- Self pick
- tomorrow / today / later
- greetings, acknowledgements, chat commentary
- phone numbers, addresses, locations, prices, invoice/payment notes
- WhatsApp UI labels, ticks, read receipts, dates
- OCR garbage and duplicated OCR text
- customer codes / BP / CFS numbers for product mapping

WHAT COUNTS AS A PRODUCT LINE:
- A line containing a cheese/product name and an explicit quantity or pack expression.
- Product names may be misspelled or abbreviated.
- A product line may say CTN, carton, box, packet, pkt, pcs, blk/block, KG, etc.
- Do NOT treat a clock time as quantity.
- Ratio/weight in a product name is NOT quantity: 70/30, 50/50, 2kg, 2.5kg, 1kg, 800gm.

KNOWN BUSINESS RULES:
- Classic shredd / classic shredded => Classic Mozzarella Shredded => FG-02-0036.
- 50/50 shredd / 50/50 shredded => Imported 50/50 Mozzarella/Cheddar Shredded 2 KG => FG-03-0024.
- TOP COW ONLY: White Shredded = White Dice; Yellow Shredded = Yellow Dice.
- For all other products, Dice, Shredded and Block are different products.
- Achha White Dice => FG-01-0124.
- Box / boxes / carton / cartons / CTN are the same unit: CTN.
- "70/30 shredded local 10 ctn" means 10 CTN, NEVER 70 or 30.
- Never invent an FG code. Local product master remains authoritative.

OUTPUT:
- Return ALL customers/orders.
- Return only real product lines.
- Customer names and product lines must remain correctly paired.
'''.strip()

NOISE = [
    r"^[-–—]?\s*forwarded\s*$",
    r"^self\s*pick\s*$",
    r"^(today|tomorrow|yesterday|later|thanks|thank you|ok|okay|salam|hello|hi)\s*$",
    r"^\d{1,2}:\d{2}(?:\s*[ap]m)?(?:\s*[a-z])?$",
    r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$",
    r"^[-= ]*ocr(?:\s+pass)?[-= ]*$",
]

def _secret(name: str) -> str | None:
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    value = os.getenv(name)
    return str(value) if value else None


def _clean_text(text: str) -> str:
    lines: List[str] = []
    seen = set()
    for raw in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if any(re.fullmatch(p, line, flags=re.I) for p in NOISE):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines)


def _parse_json(value: str) -> Dict[str, Any]:
    text = (value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("AI did not return an object")
    return data


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    result: List[Dict[str, Any]] = []
    for order in data.get("orders", []):
        customer = str(order.get("customer_name", "")).strip()
        if not customer:
            continue
        items: List[Dict[str, Any]] = []
        for item in order.get("items", []):
            product = str(item.get("product", "")).strip()
            raw = str(item.get("raw_text", "")).strip()
            if not product:
                continue
            if any(re.fullmatch(p, product, flags=re.I) for p in NOISE):
                continue
            q = item.get("quantity")
            try:
                quantity = float(q) if q is not None else None
            except (TypeError, ValueError):
                quantity = None
            if quantity is None or quantity <= 0:
                continue
            unit = str(item.get("unit", "PKT")).upper().strip()
            items.append({"raw_text": raw, "product": product, "quantity": quantity, "unit": unit})
        if items:
            result.append({"customer_name": customer, "items": items})
    return {"orders": result}


def _groq_client() -> OpenAI:
    key = _secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")


def _openai_client() -> OpenAI:
    key = _secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=key)


def _groq_text(text: str) -> Dict[str, Any]:
    client = _groq_client()
    prompt = "Parse the following WhatsApp order text. Separate EVERY customer/order block. Ignore everything except customer name and product+quantity lines.\n\n" + _clean_text(text)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=12000,
    )
    return _normalize(_parse_json(response.choices[0].message.content))


def _groq_image(image_bytes: bytes, mime: str) -> Dict[str, Any]:
    client = _groq_client()
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    prompt = '''Read the ENTIRE WhatsApp screenshot visually.

IMPORTANT: this is a multi-customer order sheet. Do NOT produce one combined order.

For every distinct customer/message block visible in the screenshot:
- identify the customer/sender/order owner
- collect only the product/order lines belonging to that customer
- ignore timestamps, Forwarded, Self pick, greetings, addresses, phone numbers, prices, dates, WhatsApp UI and all unrelated chat text
- never use a clock time as a quantity
- keep customers separate even when products are identical

Return ALL customer orders in the JSON schema.''' 
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=12000,
    )
    return _normalize(_parse_json(response.choices[0].message.content))


def _openai_text(text: str) -> Dict[str, Any]:
    client = _openai_client()
    response = client.responses.create(
        model=OPENAI_MODEL,
        store=False,
        instructions=SYSTEM,
        input=_clean_text(text),
        text={"format": {"type": "json_schema", "name": "cheese_orders", "schema": SCHEMA, "strict": True}},
    )
    return _normalize(_parse_json(response.output_text))


def _openai_image(image_bytes: bytes, mime: str) -> Dict[str, Any]:
    client = _openai_client()
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    response = client.responses.create(
        model=OPENAI_MODEL,
        store=False,
        instructions=SYSTEM,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": "Read the entire WhatsApp screenshot and return ALL customer orders separately. Ignore every non-order message and timestamp."},
            {"type": "input_image", "image_url": data_url, "detail": "high"},
        ]}],
        text={"format": {"type": "json_schema", "name": "cheese_orders", "schema": SCHEMA, "strict": True}},
    )
    return _normalize(_parse_json(response.output_text))


def _run(primary, secondary, fallback_text="") -> Dict[str, Any]:
    try:
        return primary()
    except (RateLimitError, APIError, APITimeoutError, APIConnectionError, RuntimeError, ValueError, json.JSONDecodeError):
        try:
            return secondary()
        except Exception as exc:
            return {"orders": [], "_fallback": True, "_fallback_text": fallback_text, "_fallback_reason": type(exc).__name__}


def parse_orders_text(text: str) -> Dict[str, Any]:
    return _run(lambda: _groq_text(text), lambda: _openai_text(text), text)


def parse_orders_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    return _run(lambda: _groq_image(image_bytes, mime), lambda: _openai_image(image_bytes, mime), "")


def orders_to_parser_groups(result: Dict[str, Any]) -> List[Dict[str, str]]:
    if result.get("_fallback"):
        return [{"customer_name": "", "parser_text": str(result.get("_fallback_text", ""))}]
    groups = []
    for order in result.get("orders", []):
        name = str(order.get("customer_name", "")).strip()
        lines = [name]
        for item in order.get("items", []):
            q = item.get("quantity")
            unit = item.get("unit", "PKT")
            product = item.get("product", "")
            if product and q not in (None, ""):
                q_text = str(int(q)) if float(q).is_integer() else str(q)
                lines.append(f"{q_text} {unit} {product}")
        if len(lines) > 1:
            groups.append({"customer_name": name, "parser_text": "\n".join(lines)})
    return groups


def ai_parse_order_text(text: str) -> Dict[str, Any]:
    result = parse_orders_text(text)
    first = result.get("orders", [{}])[0] if result.get("orders") else {}
    return {"customer_name": first.get("customer_name", ""), "items": first.get("items", []), **result}


def ai_parse_order_image(image_bytes: bytes) -> Dict[str, Any]:
    result = parse_orders_image(image_bytes)
    first = result.get("orders", [{}])[0] if result.get("orders") else {}
    return {"customer_name": first.get("customer_name", ""), "items": first.get("items", []), **result}


def ai_to_parser_text(result: Dict[str, Any]) -> str:
    groups = orders_to_parser_groups(result)
    return "\n\n".join(g["parser_text"] for g in groups)
