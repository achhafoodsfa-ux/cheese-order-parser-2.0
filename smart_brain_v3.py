import base64
import io
import json
import os
import re
from typing import Any, Dict, List

from openai import OpenAI, RateLimitError, APIError, APITimeoutError, APIConnectionError
from PIL import Image, ImageFilter, ImageOps
import pytesseract

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

# Deliberately excludes customer-like names such as "Red paper Nishter".
PRODUCT_HINTS = re.compile(
    r"cheese|cheddar|mozz|mozzarella|shred|shredded|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top cow|achha|allana|50/50|70/30|pizza|silver|imported|local|classic",
    re.I,
)

NOISE = [
    r"^[-–—]?\s*forwarded\s*$",
    r"^self\s*pick\s*$",
    r"^(today|tomorrow|yesterday|later|thanks|thank you|ok|okay|salam|hello|hi)\s*$",
    r"^\d{1,2}:\d{2}(?:\s*[ap]m)?(?:\s*[a-z])?$",
    r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$",
    r"^[-= ]*ocr(?:\s+pass)?[-= ]*$",
]

SYSTEM = """You are a cheese order extraction engine.
ONLY identify CUSTOMER/ORDER OWNER and PRODUCT + EXPLICIT ORDER QUANTITY.
Ignore timestamps, Forwarded, Self pick, greetings, chat commentary, addresses, phone numbers, prices, invoices, dates, WhatsApp UI and OCR garbage.
Clock times are NEVER quantities. 70/30, 50/50 and weights are product attributes, not quantities.
Every distinct customer/order block MUST remain separate. Never merge customers.
Classic shredd/shredded = FG-02-0036.
50/50 shredd/shredded = FG-03-0024.
Top Cow plain dice/white dice/white shredded = FG-02-0048.
Top Cow yellow dice/yellow shredded = FG-02-0049.
Achha White Dice = FG-01-0124.
Box/carton/CTN = CTN.
70/30 shredded local 10 ctn means 10 CTN, never 70 or 30.
Never invent product codes.""".strip()


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


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    return data if isinstance(data, dict) else {"orders": []}


def _clean_lines(text: str) -> List[str]:
    out, seen = [], set()
    for raw in str(text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if any(re.fullmatch(pattern, line, re.I) for pattern in NOISE):
            continue
        # Remove obvious WhatsApp timestamps embedded in a product line without touching the quantity.
        line = re.sub(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)?\b", " ", line, flags=re.I)
        line = re.sub(r"\b(?:10|11|12):\d{2}\s*(?:AM|PM)?[A-Z]?\b", " ", line, flags=re.I)
        line = re.sub(r"\s+", " ", line).strip()
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def _looks_product(line: str) -> bool:
    text = line.lower().strip()
    if not text or any(re.fullmatch(p, text, re.I) for p in NOISE):
        return False
    has_qty_unit = bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:ctn|carton|cartons|box|boxes|pkt|packet|packets|pcs|pc|units?)\b", text))
    has_product = bool(PRODUCT_HINTS.search(text))
    return has_qty_unit or has_product and bool(re.search(r"\b\d+(?:\.\d+)?\b", text))


def _looks_customer_heading(line: str) -> bool:
    text = re.sub(r"\s+", " ", str(line)).strip()
    if not text or any(re.fullmatch(p, text, re.I) for p in NOISE):
        return False
    if _looks_product(text):
        return False
    if re.search(r"\d", text):
        return False
    if len(text.split()) > 8:
        return False
    if re.search(r"^(forwarded|self pick|tomorrow|today|yesterday|ok|okay|thanks|thank you)$", text, re.I):
        return False
    return True


def _customer_blocks(text: str) -> List[tuple[str, List[str]]]:
    lines = _clean_lines(text)
    headings: List[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not _looks_customer_heading(line):
            continue
        # Heading must have a real product line ahead of the next heading.
        for j in range(index + 1, min(index + 10, len(lines))):
            if _looks_product(lines[j]):
                headings.append((index, line))
                break
            if _looks_customer_heading(lines[j]):
                break
    blocks = []
    for n, (position, customer) in enumerate(headings):
        stop = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        products = [line for line in lines[position + 1 : stop] if _looks_product(line)]
        if products:
            blocks.append((customer, products))
    return blocks


def _canonical_product(product: str) -> str:
    text = re.sub(r"\s+", " ", str(product or "")).strip().lower()
    if re.search(r"top\s*cow.*(yellow.*dice|yellow.*shred|yellow.*shredded)", text):
        return "Top Cow Yellow Dice"
    if re.search(r"top\s*cow.*dice", text) or re.search(r"top\s*cow.*(white\s*)?(shred|shredded)", text):
        return "Top Cow White Dice"
    if re.search(r"classic.*(shred|shredded)", text):
        return "Classic Mozzarella Shredded"
    if re.search(r"50\s*/\s*50.*(shred|shredded)", text):
        return "50/50 Shredded"
    if re.search(r"achha.*white.*dice", text):
        return "Achha White Dice"
    return str(product or "").strip()


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    orders = []
    for order in data.get("orders", []) if isinstance(data, dict) else []:
        customer = str(order.get("customer_name", "")).strip()
        if not customer:
            continue
        items = []
        for item in order.get("items", []):
            product = _canonical_product(item.get("product", ""))
            raw = str(item.get("raw_text", "")).strip()
            try:
                quantity = float(item.get("quantity"))
            except (TypeError, ValueError):
                quantity = None
            if not product or quantity is None or quantity <= 0:
                continue
            unit = str(item.get("unit", "PKT")).upper().strip()
            if unit not in {"CTN", "PKT", "KG", "PCS"}:
                unit = "PKT"
            items.append({"raw_text": raw, "product": product, "quantity": quantity, "unit": unit})
        if items:
            orders.append({"customer_name": customer, "items": items})
    return {"orders": orders}


def _groq():
    key = _secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")


def _openai():
    key = _secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=key)


def _parse_one_customer(customer: str, products: List[str]) -> Dict[str, Any]:
    block = "CUSTOMER: " + customer + "\n" + "\n".join(products)
    response = _groq().chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "Parse ONLY this ONE customer block. Never introduce another customer.\n\n" + block},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=4000,
    )
    parsed = _normalize(_parse_json(response.choices[0].message.content))
    for order in parsed["orders"]:
        order["customer_name"] = customer
    return parsed


def parse_orders_text(text: str) -> Dict[str, Any]:
    blocks = _customer_blocks(text)
    if blocks:
        orders = []
        for customer, products in blocks:
            try:
                orders.extend(_parse_one_customer(customer, products).get("orders", []))
            except Exception:
                continue
        if orders:
            return {"orders": orders}
    try:
        response = _groq().chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Parse the full order text and keep every customer separate:\n\n" + "\n".join(_clean_lines(text))},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=12000,
        )
        return _normalize(_parse_json(response.choices[0].message.content))
    except (RateLimitError, APIError, APITimeoutError, APIConnectionError, RuntimeError, ValueError, json.JSONDecodeError):
        try:
            response = _openai().responses.create(
                model=OPENAI_MODEL,
                store=False,
                instructions=SYSTEM,
                input="\n".join(_clean_lines(text)),
                text={"format": {"type": "json_schema", "name": "cheese_orders", "schema": SCHEMA, "strict": True}},
            )
            return _normalize(_parse_json(response.output_text))
        except Exception as exc:
            return {"orders": [], "_fallback": True, "_fallback_text": text, "_fallback_reason": type(exc).__name__}


def _ocr_image(image_bytes: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        width, height = image.size
        if max(width, height) < 4200:
            scale = 4200 / max(width, height)
            image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
        gray = ImageOps.autocontrast(ImageOps.grayscale(image)).filter(ImageFilter.SHARPEN)
        first = pytesseract.image_to_string(gray, config="--psm 6").strip()
        second = pytesseract.image_to_string(gray, config="--psm 11").strip()
        return "\n".join([first, second]).strip()
    except Exception:
        return ""


def _vision_image(image_bytes: bytes, mime: str) -> Dict[str, Any]:
    data_url = f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")
    response = _groq().chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": "Read the entire WhatsApp screenshot. Return every customer separately and only product + explicit quantity."},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=12000,
    )
    return _normalize(_parse_json(response.choices[0].message.content))


def parse_orders_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    # OCR/customer blocks are authoritative for separation. Vision is only a fallback.
    ocr = _ocr_image(image_bytes)
    blocks = _customer_blocks(ocr) if ocr else []
    if blocks:
        orders = []
        for customer, products in blocks:
            try:
                orders.extend(_parse_one_customer(customer, products).get("orders", []))
            except Exception:
                continue
        if orders:
            return {"orders": orders}

    try:
        visual = _vision_image(image_bytes, mime)
        if visual.get("orders"):
            return visual
    except Exception:
        pass

    if ocr:
        text_result = parse_orders_text(ocr)
        if text_result.get("orders"):
            return text_result

    return {"orders": [], "_fallback": True, "_fallback_text": ocr, "_fallback_reason": "no_readable_order_detected"}


def orders_to_parser_groups(result: Dict[str, Any]) -> List[Dict[str, str]]:
    if result.get("_fallback") and result.get("_fallback_text"):
        return [{"customer_name": "", "parser_text": str(result["_fallback_text"])}]
    groups = []
    for order in result.get("orders", []):
        customer = str(order.get("customer_name", "")).strip()
        lines = [customer] if customer else []
        for item in order.get("items", []):
            quantity = float(item["quantity"])
            quantity_text = str(int(quantity)) if quantity.is_integer() else str(quantity)
            lines.append(f"{quantity_text} {item.get('unit', 'PKT')} {item.get('product', '')}")
        if len(lines) > 1:
            groups.append({"customer_name": customer, "parser_text": "\n".join(lines)})
    return groups


def ai_parse_order_text(text: str) -> Dict[str, Any]:
    result = parse_orders_text(text)
    return {"customer_name": (result.get("orders") or [{}])[0].get("customer_name", ""), "items": (result.get("orders") or [{}])[0].get("items", []), **result}


def ai_parse_order_image(image_bytes: bytes) -> Dict[str, Any]:
    result = parse_orders_image(image_bytes)
    return {"customer_name": (result.get("orders") or [{}])[0].get("customer_name", ""), "items": (result.get("orders") or [{}])[0].get("items", []), **result}


def ai_to_parser_text(result: Dict[str, Any]) -> str:
    if result.get("_fallback") and result.get("_fallback_text"):
        return str(result["_fallback_text"])
    return "\n\n".join(group["parser_text"] for group in orders_to_parser_groups(result))
