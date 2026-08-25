import base64
import io
import json
import os
import re
from typing import Any, Dict, List

from openai import OpenAI
from PIL import Image, ImageFilter, ImageOps
import pytesseract

XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.6")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

# The critical design change is that image parsing is now TWO-STAGE:
# 1) segment the screenshot into independent WhatsApp/customer blocks;
# 2) parse products ONLY inside each block.
# We never use customer-product assignments. Any valid product may be ordered by any customer.

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string"},
                    "customer_code": {"type": "string"},
                    "message_context": {"type": "string"},
                    "lines": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "kind": {"type": "string", "enum": ["PRODUCT", "IGNORE"]},
                                "product": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string", "enum": ["CTN", "PKT", "KG", "PCS", ""]},
                            },
                            "required": ["text", "kind", "product", "quantity", "unit"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["customer", "customer_code", "message_context", "lines"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groups"],
    "additionalProperties": False,
}

LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["CUSTOMER", "PRODUCT", "IGNORE"]},
                    "text": {"type": "string"},
                    "customer": {"type": "string"},
                    "customer_code": {"type": "string"},
                    "product": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "enum": ["CTN", "PKT", "KG", "PCS", ""]},
                },
                "required": ["kind", "text", "customer", "customer_code", "product", "quantity", "unit"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}

IGNORE_WORDS = re.compile(
    r"^(forwarded|self pick|today|tomorrow|yesterday|later|thanks|thank you|ok|okay|salam|hello|hi|add in v[0-9]+)$",
    re.I,
)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s\-()]{7,}\d)")
UNIT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(ctn|carton|cartons|box|boxes|pkt|packet|packets|pcs|pc|units?|kg)\b", re.I)
PRODUCT_RE = re.compile(
    r"cheese|cheddar|mozz|mozzarella|shred|shredded|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top cow|achha|allana|50/50|70/30|pizza|silver|imported|local|classic|burger|orange",
    re.I,
)

SYSTEM_IMAGE = r'''
You are a VISUAL WHATSAPP ORDER SEGMENTER for a cheese distribution company.
This is NOT a customer-product catalog. Any customer may order ANY valid product.
Your first job is CUSTOMER SEGMENTATION. Product parsing happens only after segmentation.

Read the screenshot TOP-TO-BOTTOM and preserve the visual grouping of WhatsApp messages.
Identify each distinct customer/order block using visible sender/customer labels, message bubbles,
quoted order headers, repeated name labels, timestamps, spacing, and other visual boundaries.

CRITICAL RULES:
1. NEVER merge different customer blocks.
2. A customer block continues only until the next clearly identifiable customer/order heading.
3. A standalone person/business name immediately followed by one or more order lines is a CUSTOMER heading.
4. A message bubble/sender label is stronger evidence than a product keyword.
5. Product-like text without an explicit quantity is NOT a product order line unless it is clearly a continuation of the same order line.
6. Ignore timestamps, Forwarded labels, greetings, UI text, addresses, phone numbers, prices, comments, delivery notes, and irrelevant OCR garbage.
7. A line such as "Top cow dice 2 packet 10:31 PM" is PRODUCT with quantity 2 PKT; the time is not quantity.
8. A line such as "70/30 shredded local 10 ctn" is PRODUCT with quantity 10 CTN.
9. NEVER attach an uncertain orphan product to the previous customer. Put it in a separate REVIEW/UNKNOWN group.
10. If the screenshot genuinely does not contain enough information to identify a customer boundary, preserve a separate UNKNOWN CUSTOMER group instead of guessing.
11. Extract Customer SAP Code when visibly present; otherwise leave blank.
12. Do not invent a customer code.
13. Preserve every product line with an explicit quantity.

Return JSON groups. Each group is one independent customer/order context.
'''

SYSTEM_TEXT = r'''
You are a WhatsApp order segmenter. Customer segmentation comes FIRST.
Do not use customer-specific product assignments. Products are random and any customer may order any valid item.
A customer block is a named/sender block followed by that customer's order lines until the next customer block.
Do not combine different customers. If a boundary is unclear, create a separate UNKNOWN CUSTOMER group and flag it for review.
Ignore timestamps, greetings, addresses, phone numbers, prices and unrelated notes.
Only treat lines with an explicit quantity/unit as product lines.
'''


def _secret(name: str):
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name)


def _xai() -> OpenAI:
    key = _secret("XAI_API_KEY") or _secret("GROK_API_KEY")
    if not key:
        raise RuntimeError("XAI_API_KEY/GROK_API_KEY is not configured")
    return OpenAI(api_key=key, base_url="https://api.x.ai/v1")


def _openai() -> OpenAI:
    key = _secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=key)


def _json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = TIME_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_product_name(product: str) -> str:
    s = re.sub(r"\s+", " ", str(product or "")).strip()
    n = s.lower()
    # Special business mappings are preserved here as canonical names only.
    if "top cow" in n and "yellow" in n and ("dice" in n or "shred" in n or "shared" in n):
        return "Top Cow Yellow Dice"
    if "top cow" in n and ("dice" in n or "shred" in n or "shared" in n or "white" in n):
        return "Top Cow White Dice"
    if "danish" in n and "mozz" in n and "block" in n:
        return "Danish Mozzarella Block"
    if "red" in n and "mozz" in n and "block" in n:
        return "Red Mozz Block"
    if "blue" in n and "shred" in n:
        return "Blue Shredd"
    return s


def _is_product_row(row: Dict[str, Any]) -> bool:
    text = _clean_text(row.get("text", ""))
    product = str(row.get("product", "")).strip()
    unit = str(row.get("unit", "")).upper().strip()
    try:
        qty = float(row.get("quantity", 0) or 0)
    except Exception:
        qty = 0
    has_explicit_unit = bool(UNIT_RE.search(text)) or unit in {"CTN", "PKT", "KG", "PCS"}
    return bool(text and has_explicit_unit and qty > 0 and (product or PRODUCT_RE.search(text)))


def _looks_like_customer_name(text: str) -> bool:
    t = _clean_text(text)
    if not t or IGNORE_WORDS.fullmatch(t) or PHONE_RE.search(t):
        return False
    if re.search(r"\d", t) or UNIT_RE.search(t) or PRODUCT_RE.search(t):
        return False
    # Normal customer/party names are generally short and contain no order syntax.
    return 1 <= len(t.split()) <= 8


def _repair_group(group: Dict[str, Any]) -> Dict[str, Any]:
    name = _clean_text(group.get("customer", ""))
    code = re.search(r"\bCFS\d{3,}\b", str(group.get("customer_code", "")), re.I)
    code_value = code.group(0).upper() if code else ""
    cleaned = []
    review_lines = []

    for row in group.get("lines", []) or []:
        if not isinstance(row, dict):
            continue
        text = _clean_text(row.get("text", ""))
        if not text or IGNORE_WORDS.fullmatch(text):
            continue
        row = dict(row)
        row["text"] = text
        if _is_product_row(row):
            row["kind"] = "PRODUCT"
            row["product"] = _normalize_product_name(row.get("product", ""))
            row["unit"] = str(row.get("unit", "")).upper()
            try:
                row["quantity"] = float(row.get("quantity", 0))
            except Exception:
                row["quantity"] = 0
            cleaned.append(row)
        else:
            review_lines.append(text)

    # A group without a customer label is explicitly review-only; never silently bind it to a prior customer.
    if not name:
        name = "UNKNOWN CUSTOMER"

    return {
        "customer_name": name,
        "customer_code": code_value,
        "items": cleaned,
        "review_lines": review_lines,
    }


def _dedupe_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for g in groups:
        g = _repair_group(g)
        if not g["items"] and g["customer_name"] == "UNKNOWN CUSTOMER":
            if g["review_lines"]:
                result.append(g)
            continue
        # Keep separate groups; only merge exact repeated product lines inside the same customer later.
        result.append(g)
    return result


def _xai_image(image_bytes: bytes) -> Dict[str, Any]:
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    response = _xai().chat.completions.create(
        model=XAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_IMAGE},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Inspect the WHOLE screenshot visually. Segment every visible customer/order block first. "
                            "Do not flatten the screenshot into one customer. Preserve top-to-bottom order."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=12000,
    )
    payload = _json(response.choices[0].message.content)
    return {"orders": _dedupe_groups(payload.get("groups", [])), "source": "vision"}


def _ocr(image_bytes: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = image.size
        if max(w, h) < 4200:
            scale = 4200 / max(w, h)
            image = image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        gray = ImageOps.autocontrast(ImageOps.grayscale(image)).filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(gray, config="--psm 6")
    except Exception:
        return ""


def _xai_text(text: str) -> Dict[str, Any]:
    response = _xai().chat.completions.create(
        model=XAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_TEXT},
            {
                "role": "user",
                "content": (
                    "Segment this extracted text into independent customer blocks. "
                    "Keep every product line under its own customer and NEVER merge customer blocks.\n\n" + str(text)
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=12000,
    )
    payload = _json(response.choices[0].message.content)
    return {"orders": _dedupe_groups(payload.get("groups", [])), "source": "ocr+ai"}


def _openai_text_fallback(text: str) -> Dict[str, Any]:
    response = _openai().chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_TEXT},
            {"role": "user", "content": str(text)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    payload = _json(response.choices[0].message.content)
    return {"orders": _dedupe_groups(payload.get("groups", [])), "source": "openai+text"}


def parse_orders_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    # First choice: vision model sees the actual message bubbles and customer boundaries.
    try:
        result = _xai_image(image_bytes)
        if result.get("orders"):
            return result
    except Exception as exc:
        vision_error = f"vision: {type(exc).__name__}: {exc}"
    else:
        vision_error = "vision returned no customer groups"

    # Second choice: high-resolution OCR, then text segmentation.
    ocr_text = _ocr(image_bytes)
    if ocr_text.strip():
        try:
            result = _xai_text(ocr_text)
            if result.get("orders"):
                result["vision_error"] = vision_error
                return result
        except Exception as exc:
            ocr_error = f"ocr+ai: {type(exc).__name__}: {exc}"
        else:
            ocr_error = "ocr+ai returned no customer groups"
    else:
        ocr_error = "OCR returned no text"

    # Safe fallback: return the extracted text as review material, but DO NOT fabricate a customer.
    return {
        "orders": [],
        "source": "review",
        "_fallback": True,
        "_fallback_text": ocr_text,
        "_fallback_reason": f"{vision_error}; {ocr_error}",
    }


def parse_orders_text(text: str) -> Dict[str, Any]:
    try:
        return _xai_text(text)
    except Exception as exc:
        try:
            return _openai_text_fallback(text)
        except Exception as openai_exc:
            return {
                "orders": [],
                "source": "review",
                "_fallback": True,
                "_fallback_text": str(text),
                "_fallback_reason": f"xai={type(exc).__name__}; openai={type(openai_exc).__name__}",
            }


def orders_to_parser_groups(result: Dict[str, Any]) -> List[Dict[str, str]]:
    groups = []
    for order in result.get("orders", []) or []:
        customer = str(order.get("customer_name", "UNKNOWN CUSTOMER")).strip() or "UNKNOWN CUSTOMER"
        code = str(order.get("customer_code", "")).strip()
        header = customer if not code else f"{customer} | {code}"
        lines = [header]
        for item in order.get("items", []) or []:
            try:
                q = float(item.get("quantity", 0))
            except Exception:
                q = 0
            if q <= 0:
                continue
            q_text = str(int(q)) if q.is_integer() else str(q)
            unit = str(item.get("unit", "")).upper()
            product = _normalize_product_name(item.get("product", ""))
            if product and unit:
                lines.append(f"{q_text} {unit} {product}")
        if len(lines) > 1:
            groups.append({
                "customer_name": customer,
                "customer_code": code,
                "parser_text": "\n".join(lines),
                "review_lines": order.get("review_lines", []),
            })
    return groups


def ai_parse_order_text(text: str):
    result = parse_orders_text(text)
    first = (result.get("orders") or [{}])[0]
    return {
        "customer_name": first.get("customer_name", ""),
        "customer_code": first.get("customer_code", ""),
        "items": first.get("items", []),
        **result,
    }


def ai_parse_order_image(image_bytes: bytes):
    result = parse_orders_image(image_bytes)
    first = (result.get("orders") or [{}])[0]
    return {
        "customer_name": first.get("customer_name", ""),
        "customer_code": first.get("customer_code", ""),
        "items": first.get("items", []),
        **result,
    }


def ai_to_parser_text(result: Dict[str, Any]) -> str:
    if result.get("_fallback") and result.get("_fallback_text"):
        return str(result["_fallback_text"])
    return "\n\n".join(group["parser_text"] for group in orders_to_parser_groups(result))


__all__ = [
    "ai_parse_order_text",
    "ai_parse_order_image",
    "ai_to_parser_text",
    "orders_to_parser_groups",
    "parse_orders_text",
    "parse_orders_image",
]
