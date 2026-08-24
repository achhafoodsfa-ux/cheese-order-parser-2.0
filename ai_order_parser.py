import base64
import json
import os
from typing import Any, Dict

from openai import OpenAI

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

SCHEMA: Dict[str, Any] = {
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
}

INSTRUCTIONS = """
You are the order-understanding layer for a cheese order parser.
Read messy WhatsApp orders, OCR text, or screenshots and extract ONLY customer name and order lines.
Never invent or return SAP FG codes. Customer codes/IDs (for example CFS..., BP codes, phone numbers, invoice numbers) are NOT product identifiers and must be ignored for product mapping.
Respect these business rules while normalizing product wording:
- Classic shredd / classic shredded ALWAYS means Classic Mozzarella Shredded.
- 50/50 shredd / 50/50 shredded means Imported 50/50 Mozzarella/Cheddar Shredded 2 KG.
- For Top Cow only, White Shredded = White Dice and Yellow Shredded = Yellow Dice.
- For other products, keep Dice vs Shredded vs Block exactly as written.
- Achha White Dice means Achha White Dice.
- Preserve quantities and units exactly when clearly stated. CTN/carton/cartons = CTN; pkt/packet/packets/pcs/pc/units = PKT/PCS as appropriate; kg = KG.
- Ignore delivery instructions, greetings, phone numbers, addresses, customer codes, invoice numbers, dates, prices, and unrelated chatter.
- When wording is ambiguous, keep the best product phrase in `product` and do not invent details.
""".strip()


def _api_key() -> str | None:
    try:
        import streamlit as st
        return st.secrets.get("OPENAI_API_KEY")
    except Exception:
        return os.getenv("OPENAI_API_KEY")


def _client() -> OpenAI:
    key = _api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured in Streamlit Secrets.")
    return OpenAI(api_key=key)


def _parse_response(response) -> Dict[str, Any]:
    raw = getattr(response, "output_text", "") or ""
    if not raw:
        raise RuntimeError("OpenAI returned an empty response.")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI returned invalid structured output.") from exc


def ai_parse_order_text(text: str) -> Dict[str, Any]:
    response = _client().responses.create(
        model=MODEL,
        store=False,
        instructions=INSTRUCTIONS,
        input=text,
        text={"format": {"type": "json_schema", "name": "cheese_order", "schema": SCHEMA, "strict": True}},
    )
    return _parse_response(response)


def ai_parse_order_image(image_bytes: bytes) -> Dict[str, Any]:
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    response = _client().responses.create(
        model=MODEL,
        store=False,
        instructions=INSTRUCTIONS,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Read this order screenshot and extract the structured order."},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }
        ],
        text={"format": {"type": "json_schema", "name": "cheese_order", "schema": SCHEMA, "strict": True}},
    )
    return _parse_response(response)


def ai_to_parser_text(result: Dict[str, Any]) -> str:
    lines = ["AI_CUSTOMER"]
    for item in result.get("items", []):
        qty = item.get("quantity")
        unit = item.get("unit", "PKT")
        product = item.get("product", "")
        if product and qty not in (None, ""):
            lines.append(f"{qty} {unit} {product}")
    return "\n".join(lines)
